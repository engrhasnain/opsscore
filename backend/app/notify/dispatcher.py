"""Deliver pending notifications, with exponential backoff on failure.

Delivery is at-least-once: if a provider accepts a message but the database
commit then fails, the message is sent again on the next run. For alerts that
is the right trade; a duplicate text is better than a missing one.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from app.config import get_settings
from app.db import BYPASS_KEY, get_session_factory, utcnow
from app.enums import NotificationStatus
from app.models import Notification, Organization
from app.notify.providers import DeliveryError, get_router
from app.services import audit
from app.services.context import Ctx

logger = logging.getLogger("opscore.notify")

BASE_DELAY_SECONDS = 30
MAX_DELAY_SECONDS = 3600


@dataclass
class DispatchStats:
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    retrying: int = 0


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BASE_DELAY_SECONDS * 2 ** max(attempts - 1, 0), MAX_DELAY_SECONDS))


def _give_up(session, notification: Notification) -> None:
    """Stop retrying, and put the failure on the record so someone can act on it."""
    notification.status = NotificationStatus.FAILED
    notification.next_attempt_at = None
    logger.warning("notification failed", extra={"notification_id": str(notification.id)})
    org = session.get(Organization, notification.org_id)
    if org is not None:
        audit.record(
            session,
            Ctx.system(org, "dispatcher"),
            "notification.failed",
            "notification",
            notification.id,
            {
                "alert_id": notification.alert_id,
                "contact_id": notification.contact_id,
                "channel": notification.channel,
                "attempts": notification.attempts,
                "error": notification.last_error,
            },
        )


def deliver_pending(
    *,
    ids: list[uuid.UUID] | None = None,
    org_id: uuid.UUID | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> DispatchStats:
    """Try every due notification once. Safe to run from several workers at once."""
    now = now or utcnow()
    stats = DispatchStats()
    max_attempts = get_settings().notification_max_attempts
    router = get_router()

    session = get_session_factory()()
    session.info[BYPASS_KEY] = True
    try:
        stmt = (
            select(Notification.id)
            .where(
                Notification.status == NotificationStatus.PENDING,
                or_(Notification.next_attempt_at.is_(None), Notification.next_attempt_at <= now),
            )
            .order_by(Notification.created_at)
            .limit(limit)
        )
        if ids is not None:
            if not ids:
                return stats
            stmt = stmt.where(Notification.id.in_(ids))
        if org_id is not None:
            stmt = stmt.where(Notification.org_id == org_id)
        candidates = list(session.scalars(stmt))
        session.commit()

        for notification_id in candidates:
            notification = session.scalar(
                select(Notification)
                .where(
                    Notification.id == notification_id,
                    Notification.status == NotificationStatus.PENDING,
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if notification is None:  # another worker took it, or it is done
                session.commit()
                continue
            stats.attempted += 1
            notification.attempts += 1
            try:
                provider = router.for_channel(notification.channel)
                provider_id = provider.send(
                    notification.channel,
                    notification.recipient or "",
                    notification.subject,
                    notification.body,
                )
            except DeliveryError as exc:
                notification.last_error = str(exc)[:1000]
                if exc.permanent or notification.attempts >= max_attempts:
                    _give_up(session, notification)
                    stats.failed += 1
                else:
                    notification.next_attempt_at = now + backoff(notification.attempts)
                    stats.retrying += 1
            except Exception as exc:  # a provider bug must not kill the batch
                logger.exception("provider crashed", extra={"notification_id": str(notification.id)})
                notification.last_error = f"provider error: {type(exc).__name__}"
                if notification.attempts >= max_attempts:
                    _give_up(session, notification)
                    stats.failed += 1
                else:
                    notification.next_attempt_at = now + backoff(notification.attempts)
                    stats.retrying += 1
            else:
                notification.status = NotificationStatus.SENT
                notification.sent_at = utcnow()
                notification.provider_message_id = provider_id
                notification.next_attempt_at = None
                notification.last_error = None
                stats.sent += 1
            session.commit()
    finally:
        session.close()
    return stats
