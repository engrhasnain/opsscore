"""Turn an alert into notification rows: who, on which channel, saying what.

Text is written in each recipient's language and in the client's units.
Rows are written to the outbox here and delivered by ``app.notify.dispatcher``.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import Channel, Locale, NotificationStatus, UnitSystem
from app.i18n import severity_label, t
from app.models import Alert, Asset, Contact, Event, EventType, Notification, Organization, Rule, Site, WorkOrder
from app.units import format_quantity

logger = logging.getLogger("opscore.notifications")

SHORT_BODY_LIMIT = 1500  # SMS and WhatsApp
NL = chr(10)
LATE_REPORT_MINUTES = 15  # older readings are labelled so nobody mistakes them for live ones


@dataclass
class Recipient:
    contact: Contact
    channel: Channel
    address: str | None


def resolve_recipients(session: Session, org_id: uuid.UUID, actions: list[dict]) -> list[Recipient]:
    """Every (contact, channel) pair the rule's notify actions point at, without repeats."""
    recipients: list[Recipient] = []
    seen: set[tuple[uuid.UUID, Channel]] = set()
    for action in actions:
        if action.get("type") != "notify":
            continue
        ids = [uuid.UUID(c) for c in action.get("contact_ids", [])]
        roles = action.get("contact_roles", [])
        contacts: list[Contact] = []
        if ids:
            contacts += session.scalars(
                select(Contact).where(Contact.org_id == org_id, Contact.id.in_(ids), Contact.is_active.is_(True))
            )
        if roles:
            contacts += session.scalars(
                select(Contact).where(
                    Contact.org_id == org_id,
                    func.lower(Contact.role_label).in_(roles),
                    Contact.is_active.is_(True),
                )
            )
        for contact in sorted(contacts, key=lambda c: (c.name, str(c.id))):
            for channel_value in action["channels"]:
                channel = Channel(channel_value)
                if (contact.id, channel) in seen:
                    continue
                seen.add((contact.id, channel))
                recipients.append(Recipient(contact, channel, _address(contact, channel)))
    return recipients


def _address(contact: Contact, channel: Channel) -> str | None:
    return {
        Channel.EMAIL: contact.email,
        Channel.SMS: contact.phone,
        Channel.WHATSAPP: contact.whatsapp or contact.phone,
    }[channel]


def local_time(moment: datetime, timezone: str) -> str:
    try:
        zone = ZoneInfo(timezone)
    except Exception:
        zone = ZoneInfo("UTC")
        timezone = "UTC"
    return f"{moment.astimezone(zone):%Y-%m-%d %H:%M} ({timezone})"


def format_attributes(
    values: dict[str, Any], schema: list[dict], system: UnitSystem, locale: Locale | None = None
) -> list[tuple[str, str]]:
    by_name = {item["name"]: item for item in schema}
    lines = []
    for name in sorted(values):
        value = values[name]
        definition = by_name.get(name, {})
        label = definition.get("label") or name.replace("_", " ").capitalize()
        unit = definition.get("unit")
        if unit and isinstance(value, int | float) and not isinstance(value, bool):
            shown = format_quantity(float(value), unit, system, locale)
        elif isinstance(value, bool):
            shown = "✓" if value else "✗"
        else:
            shown = str(value)
        lines.append((label, shown))
    return lines


def compose(
    *,
    org: Organization,
    alert: Alert,
    event: Event,
    event_type: EventType,
    site: Site | None,
    asset: Asset | None,
    locale: Locale,
    channel: Channel,
    reason: str,
) -> tuple[str, str]:
    """Subject and body for one recipient."""
    severity = severity_label(alert.severity, locale).upper()
    prefix = ""
    if reason == "escalated":
        prefix = f"{t('notify.escalated', locale)}: "
    elif reason == "reminder":
        prefix = f"{t('notify.reminder', locale)}: "
    subject = f"[{severity}] {prefix}{alert.title}"[:300]

    timezone = (site.timezone if site and site.timezone else None) or org.timezone
    lines = [
        f"{t('notify.label.event', locale)}: {event_type.name}",
    ]
    if site:
        lines.append(f"{t('notify.label.site', locale)}: {site.name} ({site.code})")
    if asset:
        lines.append(f"{t('notify.label.asset', locale)}: {asset.name} ({asset.code})")
    lines.append(f"{t('notify.label.time', locale)}: {local_time(event.occurred_at, timezone)}")
    late = (event.received_at - event.occurred_at).total_seconds() // 60 if event.received_at else 0
    if late >= LATE_REPORT_MINUTES:
        lines.append(t("notify.late_report", locale).format(minutes=int(late)))
    details = format_attributes(event.attributes, event_type.attributes_schema, org.unit_system, locale)
    if details:
        lines.append(f"{t('notify.label.details', locale)}:")
        lines += [f"  - {label}: {shown}" for label, shown in details]
    if event.description:
        lines.append(event.description)
    if alert.occurrence_count > 1:
        lines.append(f"{t('notify.label.occurrences', locale)}: {alert.occurrence_count}")
    lines.append(f"{t('notify.label.reference', locale)}: {str(alert.id)[:8]}")

    if channel == Channel.EMAIL:
        body = "\n".join(lines)
    else:
        body = f"{subject}\n" + "\n".join(lines)
        if len(body) > SHORT_BODY_LIMIT:
            body = body[: SHORT_BODY_LIMIT - 1] + "…"
    return subject, body


def enqueue_for_alert(
    session: Session,
    *,
    org: Organization,
    rule: Rule,
    alert: Alert,
    event: Event,
    event_type: EventType,
    site: Site | None,
    asset: Asset | None,
    reason: str,
) -> list[Notification]:
    recipients = resolve_recipients(session, org.id, rule.actions)
    created: list[Notification] = []
    for recipient in recipients:
        locale = Locale(recipient.contact.locale or org.default_locale)
        subject, body = compose(
            org=org,
            alert=alert,
            event=event,
            event_type=event_type,
            site=site,
            asset=asset,
            locale=locale,
            channel=recipient.channel,
            reason=reason,
        )
        notification = Notification(
            org_id=org.id,
            alert_id=alert.id,
            contact_id=recipient.contact.id,
            channel=recipient.channel,
            recipient=recipient.address,
            subject=subject,
            body=body,
            status=NotificationStatus.PENDING if recipient.address else NotificationStatus.SKIPPED,
            last_error=None if recipient.address else f"contact has no {recipient.channel.value} address",
        )
        session.add(notification)
        created.append(notification)
    session.flush()
    if rule_notifies(rule) and not recipients:
        logger.warning(
            "rule matched but resolved no recipients",
            extra={"rule_id": str(rule.id), "alert_id": str(alert.id)},
        )
    return created


def work_order_recipients(session: Session, work_order: WorkOrder) -> list[Recipient]:
    """The assignee if there is one; otherwise whoever the rule that opened it notifies."""
    if work_order.assignee_contact_id:
        contact = session.scalar(
            select(Contact).where(
                Contact.org_id == work_order.org_id,
                Contact.id == work_order.assignee_contact_id,
                Contact.is_active.is_(True),
            )
        )
        if contact is None:
            return []
        channel = Channel.WHATSAPP if contact.whatsapp else Channel.SMS
        recipients = [Recipient(contact, channel, _address(contact, channel))]
        if contact.email:
            recipients.append(Recipient(contact, Channel.EMAIL, contact.email))
        return recipients
    if work_order.alert_id:
        alert = session.get(Alert, work_order.alert_id)
        rule = session.get(Rule, alert.rule_id) if alert else None
        if rule is not None:
            return resolve_recipients(session, work_order.org_id, rule.actions)
    return []


def enqueue_for_work_order(
    session: Session,
    *,
    org: Organization,
    work_order: WorkOrder,
    site: Site | None,
    reason: str,
    recipients: list[Recipient] | None = None,
) -> list[Notification]:
    """Tell people about a work order: "new" (just assigned) or "overdue"."""
    if recipients is None:
        recipients = work_order_recipients(session, work_order)
    timezone = (site.timezone if site and site.timezone else None) or org.timezone
    created: list[Notification] = []
    for recipient in recipients:
        locale = Locale(recipient.contact.locale or org.default_locale)
        heading = t(f"notify.work_order.{reason}", locale)
        priority = t(f"priority.{work_order.priority}", locale)
        subject = f"[{heading}] {work_order.title}"[:300]
        lines = [f"{t('notify.label.priority', locale)}: {priority}"]
        if site:
            lines.append(f"{t('notify.label.site', locale)}: {site.name} ({site.code})")
        if work_order.due_at:
            lines.append(f"{t('notify.label.due', locale)}: {local_time(work_order.due_at, timezone)}")
        lines.append(f"{t('notify.label.reference', locale)}: {str(work_order.id)[:8]}")
        body = NL.join(lines) if recipient.channel == Channel.EMAIL else f"{subject}{NL}" + NL.join(lines)
        notification = Notification(
            org_id=org.id,
            alert_id=work_order.alert_id,
            contact_id=recipient.contact.id,
            channel=recipient.channel,
            recipient=recipient.address,
            subject=subject,
            body=body[:SHORT_BODY_LIMIT] if recipient.channel != Channel.EMAIL else body,
            status=NotificationStatus.PENDING if recipient.address else NotificationStatus.SKIPPED,
            last_error=None if recipient.address else f"contact has no {recipient.channel.value} address",
        )
        session.add(notification)
        created.append(notification)
    session.flush()
    return created


def rule_notifies(rule: Rule) -> bool:
    return any(action.get("type") == "notify" for action in rule.actions)
