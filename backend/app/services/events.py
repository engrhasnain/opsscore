"""Event intake: validate, store, run the rules, raise or merge alerts.

    event in -> validated -> stored (immutable) -> rules evaluated
             -> alert created / merged / escalated -> work order -> notifications

Repeated matches fold into the live alert for the same rule and location, so a
storm of identical events on a strike day produces one alert with a count, not
hundreds of texts.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.enums import SEVERITY_RANK, AlertStatus, NotificationStatus, Severity, WorkOrderPriority, WorkOrderStatus
from app.errors import Conflict, NotFound, ValidationFailed
from app.models import (
    Alert,
    AlertEvent,
    Asset,
    Contact,
    Event,
    EventType,
    Notification,
    Organization,
    Rule,
    Site,
    WorkOrder,
)
from app.schemas.operations import EventIn
from app.services import attributes as attr
from app.services import audit, notifications
from app.services import rules as rules_engine
from app.services.catalog import event_type_by_key, site_by_code
from app.services.context import Ctx
from app.services.notifications import local_time, rule_notifies
from app.services.scoping import get_or_404, scoped
from app.services.templating import render
from app.services.validation import code as normalize_code

logger = logging.getLogger("opscore.events")


@dataclass
class Resolved:
    event_type: EventType
    site: Site | None
    asset: Asset | None
    severity: Severity
    occurred_at: datetime
    attributes: dict
    warnings: list[str] = field(default_factory=list)


@dataclass
class AlertOutcome:
    alert: Alert
    rule: Rule
    outcome: str  # created | merged | escalated | reminded | duplicate
    notifications: list[Notification] = field(default_factory=list)
    work_order: WorkOrder | None = None


@dataclass
class IngestResult:
    event: Event
    created: bool
    outcomes: list[AlertOutcome]
    warnings: list[str]

    @property
    def pending_notification_ids(self) -> list[uuid.UUID]:
        return [n.id for o in self.outcomes for n in o.notifications if n.status == "pending"]


# --------------------------------------------------------------- resolution


def _resolve_location(session: Session, ctx: Ctx, data: EventIn) -> tuple[Site | None, Asset | None]:
    asset = None
    if data.asset_id is not None:
        asset = session.scalar(scoped(Asset, ctx.org_id).where(Asset.id == data.asset_id))
        if asset is None:
            raise ValidationFailed("Unknown asset_id.", code="UNKNOWN_ASSET")
    if data.asset_code:
        by_code = session.scalar(
            scoped(Asset, ctx.org_id).where(Asset.code == normalize_code(data.asset_code, field="asset_code"))
        )
        if by_code is None:
            raise ValidationFailed(f"No asset with code {data.asset_code}.", code="UNKNOWN_ASSET")
        if asset is not None and asset.id != by_code.id:
            raise ValidationFailed("asset_id and asset_code point at different assets.")
        asset = by_code

    site = None
    if data.site_id is not None:
        site = session.scalar(scoped(Site, ctx.org_id).where(Site.id == data.site_id))
        if site is None:
            raise ValidationFailed("Unknown site_id.", code="UNKNOWN_SITE")
    if data.site_code:
        by_code = site_by_code(session, ctx.org_id, data.site_code)
        if by_code is None:
            raise ValidationFailed(f"No site with code {data.site_code}.", code="UNKNOWN_SITE")
        if site is not None and site.id != by_code.id:
            raise ValidationFailed("site_id and site_code point at different sites.")
        site = by_code

    if asset is not None:
        if site is not None and asset.site_id != site.id:
            raise ValidationFailed(f"Asset {asset.code} is not at site {site.code}.", code="ASSET_NOT_AT_SITE")
        site = site or session.get(Site, asset.site_id)
        if not asset.is_active:
            raise ValidationFailed(f"Asset {asset.code} is deactivated.", code="ASSET_INACTIVE")
    if site is not None and not site.is_active:
        raise ValidationFailed(f"Site {site.code} is deactivated.", code="SITE_INACTIVE")
    return site, asset


def resolve(session: Session, ctx: Ctx, data: EventIn, *, now: datetime) -> Resolved:
    """Validate an incoming event without writing anything."""
    event_type = event_type_by_key(session, ctx.org_id, data.event_type)
    if event_type is None:
        raise ValidationFailed(f"Unknown event type {data.event_type!r}.", code="UNKNOWN_EVENT_TYPE")
    if not event_type.is_active:
        raise ValidationFailed(f"Event type {event_type.key} is deactivated.", code="EVENT_TYPE_INACTIVE")

    site, asset = _resolve_location(session, ctx, data)

    settings = get_settings()
    occurred_at = data.occurred_at or now
    if occurred_at > now + timedelta(seconds=settings.event_max_future_skew_seconds):
        raise ValidationFailed("occurred_at is in the future. Check the device clock.", code="EVENT_IN_FUTURE")
    if occurred_at < now - timedelta(days=settings.event_max_age_days):
        raise ValidationFailed(
            f"occurred_at is more than {settings.event_max_age_days} days old.", code="EVENT_TOO_OLD"
        )

    checked = attr.validate_values(event_type.attributes_schema, data.attributes)
    return Resolved(
        event_type=event_type,
        site=site,
        asset=asset,
        severity=data.severity or event_type.default_severity,
        occurred_at=occurred_at,
        attributes=checked.values,
        warnings=checked.warnings,
    )


def _context_values(ctx: Ctx, resolved: Resolved, source_type: str) -> dict:
    timezone = (resolved.site.timezone if resolved.site and resolved.site.timezone else None) or ctx.org.timezone
    return rules_engine.build_context(
        severity=resolved.severity,
        event_type_key=resolved.event_type.key,
        source_type=source_type,
        occurred_at=resolved.occurred_at,
        timezone=timezone,
        attributes=resolved.attributes,
        site=(
            {"code": resolved.site.code, "kind": resolved.site.kind, "name": resolved.site.name}
            if resolved.site
            else None
        ),
        asset=(
            {
                "code": resolved.asset.code,
                "type": resolved.asset.asset_type,
                "name": resolved.asset.name,
                "criticality": resolved.asset.criticality,
            }
            if resolved.asset
            else None
        ),
    )


def _template_values(ctx: Ctx, resolved: Resolved) -> dict[str, str]:
    timezone = (resolved.site.timezone if resolved.site and resolved.site.timezone else None) or ctx.org.timezone
    values = {
        "event_type": resolved.event_type.name,
        "severity": str(resolved.severity),
        "occurred_at": local_time(resolved.occurred_at, timezone),
        "site.code": resolved.site.code if resolved.site else "",
        "site.name": resolved.site.name if resolved.site else "",
        "asset.code": resolved.asset.code if resolved.asset else "",
        "asset.name": resolved.asset.name if resolved.asset else "",
    }
    for key, value in resolved.attributes.items():
        values[f"attributes.{key}"] = str(value)
    return values


def _matching_rules(session: Session, ctx: Ctx, event_type: EventType) -> list[Rule]:
    return list(
        session.scalars(
            scoped(Rule, ctx.org_id)
            .where(
                Rule.is_active.is_(True),
                or_(Rule.event_type_id == event_type.id, Rule.event_type_id.is_(None)),
            )
            .order_by(Rule.priority, Rule.created_at)
        )
    )


# ------------------------------------------------------------------ intake


def ingest(session: Session, ctx: Ctx, data: EventIn, *, idempotency_key: str | None = None) -> IngestResult:
    if idempotency_key and data.idempotency_key and idempotency_key != data.idempotency_key:
        raise ValidationFailed("Idempotency-Key header and body idempotency_key differ.")
    key = data.idempotency_key or idempotency_key
    now = utcnow()

    if key:
        existing = _by_idempotency_key(session, ctx, key)
        if existing is not None:
            return _duplicate(session, ctx, existing, data)

    resolved = resolve(session, ctx, data, now=now)
    # Take the organization lock (which the audit trail needs anyway) before any alert
    # row lock, so every writer locks in the same order and PostgreSQL cannot deadlock.
    session.execute(select(Organization.id).where(Organization.id == ctx.org_id).with_for_update()).scalar_one()
    event = Event(
        id=uuid.uuid4(),
        org_id=ctx.org_id,
        event_type_id=resolved.event_type.id,
        site_id=resolved.site.id if resolved.site else None,
        asset_id=resolved.asset.id if resolved.asset else None,
        severity=resolved.severity,
        occurred_at=resolved.occurred_at,
        received_at=now,
        attributes=resolved.attributes,
        description=data.description,
        source_type=ctx.actor.type,
        source_id=ctx.actor.id,
        idempotency_key=key,
    )
    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
    except IntegrityError:
        # Lost a race with an identical retry; return the winner.
        existing = _by_idempotency_key(session, ctx, key) if key else None
        if existing is None:
            raise
        return _duplicate(session, ctx, existing, data)

    values = _context_values(ctx, resolved, str(ctx.actor.type))
    outcomes = []
    for rule in _matching_rules(session, ctx, resolved.event_type):
        if rules_engine.evaluate(rule.conditions, rule.match, values):
            outcomes.append(_raise_alert(session, ctx, rule, event, resolved, now))
    return IngestResult(event=event, created=True, outcomes=outcomes, warnings=resolved.warnings)


def _by_idempotency_key(session: Session, ctx: Ctx, key: str) -> Event | None:
    return session.scalar(scoped(Event, ctx.org_id).where(Event.idempotency_key == key))


def _duplicate(session: Session, ctx: Ctx, existing: Event, data: EventIn) -> IngestResult:
    event_type = event_type_by_key(session, ctx.org_id, data.event_type)
    if event_type is None or event_type.id != existing.event_type_id:
        raise Conflict(
            "This idempotency key was already used for a different event.",
            code="IDEMPOTENCY_KEY_REUSED",
        )
    alerts = session.execute(
        select(Alert, Rule)
        .join(AlertEvent, AlertEvent.alert_id == Alert.id)
        .join(Rule, Rule.id == Alert.rule_id)
        .where(AlertEvent.event_id == existing.id, Alert.org_id == ctx.org_id)
    ).all()
    outcomes = [AlertOutcome(alert=a, rule=r, outcome="duplicate") for a, r in alerts]
    return IngestResult(event=existing, created=False, outcomes=outcomes, warnings=[])


def _alert_title(rule: Rule, resolved: Resolved) -> str:
    where = resolved.asset.name if resolved.asset else resolved.site.name if resolved.site else None
    title = f"{rule.name} · {where}" if where else rule.name
    return title[:300]


def _raise_alert(
    session: Session, ctx: Ctx, rule: Rule, event: Event, resolved: Resolved, now: datetime
) -> AlertOutcome:
    severity = Severity(rule.severity_override or event.severity)
    dedupe_key = _dedupe_key(rule, event)

    live = _live_alert(session, ctx, dedupe_key)
    if live is None:
        alert = Alert(
            id=uuid.uuid4(),
            org_id=ctx.org_id,
            rule_id=rule.id,
            first_event_id=event.id,
            site_id=event.site_id,
            asset_id=event.asset_id,
            title=_alert_title(rule, resolved),
            severity=severity,
            status=AlertStatus.OPEN,
            dedupe_key=dedupe_key,
            occurrence_count=1,
            first_seen_at=event.occurred_at,
            last_seen_at=event.occurred_at,
        )
        try:
            with session.begin_nested():
                session.add(alert)
                session.add(AlertEvent(org_id=ctx.org_id, alert_id=alert.id, event_id=event.id))
                session.flush()
        except IntegrityError:
            # A concurrent event created the live alert first; merge into it.
            live = _live_alert(session, ctx, dedupe_key)
            if live is None:
                raise
        else:
            return _on_new_alert(session, ctx, rule, alert, event, resolved, now)

    return _merge_into(session, ctx, rule, live, event, resolved, severity, now)


def _dedupe_key(rule: Rule, event: Event) -> str:
    """Repeat events fold into one live alert per rule and location.

    Events that belong to a conversation (assistant escalations) are also split per
    conversation: two drivers asking for help are two problems, not one.
    """
    key = f"{rule.id}:{event.site_id or '-'}:{event.asset_id or '-'}"
    conversation = (event.attributes or {}).get("conversation_id")
    return f"{key}:{conversation}" if conversation else key


def _deliverable(sent: list[Notification]) -> list[Notification]:
    """Rows that will actually reach someone (not skipped for a missing address)."""
    return [n for n in sent if n.status == NotificationStatus.PENDING]


def _live_alert(session: Session, ctx: Ctx, dedupe_key: str) -> Alert | None:
    return session.scalar(
        scoped(Alert, ctx.org_id)
        .where(Alert.dedupe_key == dedupe_key, Alert.status != AlertStatus.RESOLVED)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _on_new_alert(session, ctx, rule, alert, event, resolved, now) -> AlertOutcome:
    work_order = _create_work_order_from_rule(session, ctx, rule, alert, resolved, now)
    sent = notifications.enqueue_for_alert(
        session,
        org=ctx.org,
        rule=rule,
        alert=alert,
        event=event,
        event_type=resolved.event_type,
        site=resolved.site,
        asset=resolved.asset,
        reason="new",
    )
    if _deliverable(sent):
        alert.last_notified_at = now
    audit.record(
        session,
        ctx,
        "alert.raised",
        "alert",
        alert.id,
        {"rule_id": rule.id, "event_id": event.id, "severity": alert.severity, "title": alert.title},
    )
    if rule_notifies(rule) and not _deliverable(sent):
        audit.record(
            session,
            ctx,
            "alert.no_recipients",
            "alert",
            alert.id,
            {"rule_id": rule.id, "skipped": len(sent)},
        )
    session.flush()
    return AlertOutcome(alert=alert, rule=rule, outcome="created", notifications=sent, work_order=work_order)


def _merge_into(session, ctx, rule, alert, event, resolved, severity, now) -> AlertOutcome:
    session.add(AlertEvent(org_id=ctx.org_id, alert_id=alert.id, event_id=event.id))
    alert.occurrence_count += 1
    alert.first_seen_at = min(alert.first_seen_at, event.occurred_at)
    alert.last_seen_at = max(alert.last_seen_at, event.occurred_at)

    reason = None
    outcome = "merged"
    if SEVERITY_RANK[severity] > SEVERITY_RANK[Severity(alert.severity)]:
        previous = alert.severity
        alert.severity = severity
        reason, outcome = "escalated", "escalated"
        # Someone acknowledged a lesser problem; a worse one needs acknowledging again.
        reopened = alert.status == AlertStatus.ACKNOWLEDGED
        if reopened:
            alert.status = AlertStatus.OPEN
        audit.record(
            session,
            ctx,
            "alert.escalated",
            "alert",
            alert.id,
            {"from": previous, "to": severity, "event_id": event.id, "reopened": reopened},
        )
    elif (
        alert.status == AlertStatus.OPEN
        and rule.renotify_after_seconds
        and (
            alert.last_notified_at is None
            or now - alert.last_notified_at >= timedelta(seconds=rule.renotify_after_seconds)
        )
    ):
        reason, outcome = "reminder", "reminded"

    sent: list[Notification] = []
    if reason:
        sent = notifications.enqueue_for_alert(
            session,
            org=ctx.org,
            rule=rule,
            alert=alert,
            event=event,
            event_type=resolved.event_type,
            site=resolved.site,
            asset=resolved.asset,
            reason=reason,
        )
        if _deliverable(sent):
            alert.last_notified_at = now
    session.flush()
    return AlertOutcome(alert=alert, rule=rule, outcome=outcome, notifications=sent)


def _create_work_order_from_rule(session, ctx, rule, alert, resolved, now) -> WorkOrder | None:
    action = next((a for a in rule.actions if a.get("type") == "create_work_order"), None)
    if action is None:
        return None
    values = _template_values(ctx, resolved)
    assignee_id = None
    if action.get("assignee_contact_id"):
        contact = session.scalar(
            scoped(Contact, ctx.org_id).where(
                Contact.id == uuid.UUID(action["assignee_contact_id"]), Contact.is_active.is_(True)
            )
        )
        assignee_id = contact.id if contact else None
    work_order = WorkOrder(
        org_id=ctx.org_id,
        alert_id=alert.id,
        site_id=alert.site_id,
        asset_id=alert.asset_id,
        title=render(action["title"], values, max_length=300),
        description=render(action["description"], values, max_length=4000) if action.get("description") else None,
        priority=WorkOrderPriority(action.get("priority", "normal")),
        status=WorkOrderStatus.OPEN,
        assignee_contact_id=assignee_id,
        due_at=now + timedelta(hours=action["due_in_hours"]) if action.get("due_in_hours") else None,
    )
    session.add(work_order)
    session.flush()
    audit.record(
        session,
        ctx,
        "work_order.created",
        "work_order",
        work_order.id,
        {"alert_id": alert.id, "rule_id": rule.id, "title": work_order.title, "priority": work_order.priority},
    )
    if assignee_id:
        notifications.enqueue_for_work_order(
            session, org=ctx.org, work_order=work_order, site=resolved.site, reason="new"
        )
    return work_order


# --------------------------------------------------------------- dry runs


@dataclass
class RuleTestResult:
    matched: bool
    severity: Severity | None
    recipients: list[dict]
    work_order_title: str | None
    warnings: list[str]


def dry_run_rule(session: Session, ctx: Ctx, rule_id: uuid.UUID, data: EventIn) -> RuleTestResult:
    """Show what a rule would do with a sample event. Writes nothing."""
    rule = get_or_404(session, Rule, ctx.org_id, rule_id, label="Rule")
    resolved = resolve(session, ctx, data, now=utcnow())
    warnings = list(resolved.warnings)
    if rule.event_type_id and rule.event_type_id != resolved.event_type.id:
        warnings.append("this rule only applies to a different event type")
        return RuleTestResult(False, None, [], None, warnings)
    if not rule.is_active:
        warnings.append("this rule is deactivated and will not run")

    values = _context_values(ctx, resolved, str(ctx.actor.type))
    if not rules_engine.evaluate(rule.conditions, rule.match, values):
        return RuleTestResult(False, None, [], None, warnings)

    recipients = [
        {
            "contact_id": str(r.contact.id),
            "name": r.contact.name,
            "channel": r.channel.value,
            "deliverable": r.address is not None,
        }
        for r in notifications.resolve_recipients(session, ctx.org_id, rule.actions)
    ]
    if rule_notifies(rule) and not recipients:
        warnings.append("no active contacts match this rule's recipients")
    action = next((a for a in rule.actions if a.get("type") == "create_work_order"), None)
    title = render(action["title"], _template_values(ctx, resolved), max_length=300) if action else None
    return RuleTestResult(True, Severity(rule.severity_override or resolved.severity), recipients, title, warnings)


def get_event(session: Session, ctx: Ctx, event_id: uuid.UUID) -> Event:
    event = session.scalar(scoped(Event, ctx.org_id).where(Event.id == event_id))
    if event is None:
        raise NotFound("Event not found.")
    return event
