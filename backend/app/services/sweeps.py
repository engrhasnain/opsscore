"""Time-based follow-ups, run by the worker, so nothing depends on someone remembering.

- An alert nobody has acknowledged is sent again to the same people on an interval
  (the rule's ``renotify_after_seconds``, or a default by severity).
- A work order past its due time is reported once to its assignee, or to the people
  the rule that opened it notifies.

Both run across all tenants in a system session and leave an audit entry per action.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.enums import AlertStatus, NotificationStatus, Severity, WorkOrderStatus
from app.models import Alert, AlertEvent, Asset, Event, EventType, Notification, Organization, Rule, Site, WorkOrder
from app.services import audit, notifications
from app.services.context import Ctx

logger = logging.getLogger("opscore.sweeps")

# How long an unacknowledged alert waits before the same people are told again,
# when its rule does not set its own interval.
DEFAULT_REMINDER_SECONDS = {
    Severity.CRITICAL: 10 * 60,
    Severity.HIGH: 30 * 60,
    Severity.MEDIUM: 60 * 60,
    Severity.LOW: 2 * 60 * 60,
}


def reminder_interval(rule: Rule, severity: Severity) -> timedelta | None:
    seconds = rule.renotify_after_seconds or DEFAULT_REMINDER_SECONDS.get(Severity(severity))
    return timedelta(seconds=seconds) if seconds else None


def _deliverable(sent: list[Notification]) -> int:
    return sum(1 for n in sent if n.status == NotificationStatus.PENDING)


def sweep_alerts(session: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """Remind people about open alerts nobody has acknowledged. Returns reminders sent."""
    now = now or utcnow()
    reminded = 0
    open_alerts = list(
        session.scalars(select(Alert).where(Alert.status == AlertStatus.OPEN).order_by(Alert.created_at).limit(limit))
    )
    for alert in open_alerts:
        rule = session.get(Rule, alert.rule_id)
        if rule is None or not notifications.rule_notifies(rule):
            continue
        interval = reminder_interval(rule, alert.severity)
        last = alert.last_notified_at or alert.created_at
        if interval is None or now - last < interval:
            continue
        # Lock and re-check so two workers don't both remind.
        alert = session.scalar(
            select(Alert)
            .where(Alert.id == alert.id, Alert.status == AlertStatus.OPEN)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if alert is None or now - (alert.last_notified_at or alert.created_at) < interval:
            continue
        event = session.scalar(
            select(Event)
            .join(AlertEvent, AlertEvent.event_id == Event.id)
            .where(AlertEvent.alert_id == alert.id)
            .order_by(Event.occurred_at.desc())
            .limit(1)
        )
        org = session.get(Organization, alert.org_id)
        if event is None or org is None:
            continue
        sent = notifications.enqueue_for_alert(
            session,
            org=org,
            rule=rule,
            alert=alert,
            event=event,
            event_type=session.get(EventType, event.event_type_id),
            site=session.get(Site, alert.site_id) if alert.site_id else None,
            asset=session.get(Asset, alert.asset_id) if alert.asset_id else None,
            reason="reminder",
        )
        # Move the clock even when nobody could be reached, or every pass would retry.
        alert.last_notified_at = now
        audit.record(
            session,
            Ctx.system(org, "worker"),
            "alert.reminder_sent",
            "alert",
            alert.id,
            {
                "notifications": _deliverable(sent),
                "minutes_unacknowledged": int((now - alert.created_at).total_seconds() // 60),
            },
        )
        session.commit()
        reminded += 1
    return reminded


def sweep_work_orders(session: Session, *, now: datetime | None = None, limit: int = 200) -> int:
    """Tell people, once, about work orders past their due time. Returns how many."""
    now = now or utcnow()
    told = 0
    overdue = list(
        session.scalars(
            select(WorkOrder)
            .where(
                WorkOrder.status.in_([WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS]),
                WorkOrder.due_at.is_not(None),
                WorkOrder.due_at <= now,
                WorkOrder.overdue_notified_at.is_(None),
            )
            .order_by(WorkOrder.due_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for work_order in overdue:
        org = session.get(Organization, work_order.org_id)
        if org is None:
            continue
        sent = notifications.enqueue_for_work_order(
            session,
            org=org,
            work_order=work_order,
            site=session.get(Site, work_order.site_id) if work_order.site_id else None,
            reason="overdue",
        )
        work_order.overdue_notified_at = now
        audit.record(
            session,
            Ctx.system(org, "worker"),
            "work_order.overdue",
            "work_order",
            work_order.id,
            {
                "due_at": work_order.due_at,
                "minutes_late": int((now - work_order.due_at).total_seconds() // 60),
                "notifications": _deliverable(sent),
            },
        )
        told += 1
    session.commit()
    return told
