"""What happens at runtime: rules, events, alerts, work orders, notifications."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, JSONType, UTCDateTime
from app.enums import (
    ActorType,
    AlertStatus,
    Channel,
    NotificationStatus,
    Severity,
    WorkOrderPriority,
    WorkOrderStatus,
)
from app.models.base import IdMixin, TenantMixin, TimestampMixin, enum_column


class Rule(IdMixin, TimestampMixin, TenantMixin, Base):
    """When an event like this happens, raise an alert and do these things.

    ``conditions`` and ``actions`` are validated JSON documents
    (see ``app.services.rules``), so clients configure behaviour without code.
    """

    __tablename__ = "rules"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    event_type_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("event_types.id", ondelete="RESTRICT"), index=True
    )
    match: Mapped[str] = mapped_column(String(8), nullable=False, default="all")
    conditions: Mapped[list[dict]] = mapped_column(JSONType, nullable=False, default=list)
    actions: Mapped[list[dict]] = mapped_column(JSONType, nullable=False, default=list)
    severity_override: Mapped[Severity | None] = enum_column(Severity, "severity_override")
    renotify_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Event(IdMixin, TenantMixin, Base):
    """Something that happened. Immutable once stored: it is evidence."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key"),
        Index("ix_events_org_occurred", "org_id", "occurred_at"),
    )

    event_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("event_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("assets.id", ondelete="RESTRICT"), index=True)
    severity: Mapped[Severity] = enum_column(Severity, "severity", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(String(2000))
    source_type: Mapped[ActorType] = enum_column(ActorType, "source_type", nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))


class Alert(IdMixin, TimestampMixin, TenantMixin, Base):
    """A rule matched. Repeat matches fold into the open alert instead of spamming."""

    __tablename__ = "alerts"
    __table_args__ = (
        # One live alert per rule and location; concurrent events merge into it.
        Index(
            "uq_alerts_live_dedupe",
            "org_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
            sqlite_where=text("status <> 'resolved'"),
        ),
        Index("ix_alerts_org_status_severity", "org_id", "status", "severity"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    first_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sites.id"), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("assets.id"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[Severity] = enum_column(Severity, "severity", nullable=False)
    status: Mapped[AlertStatus] = enum_column(AlertStatus, "status", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolution_note: Mapped[str | None] = mapped_column(String(2000))


class AlertEvent(TenantMixin, Base):
    """Every event that contributed to an alert: the evidence trail."""

    __tablename__ = "alert_events"

    alert_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class WorkOrder(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (Index("ix_work_orders_org_status", "org_id", "status"),)

    alert_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("alerts.id", ondelete="SET NULL"), index=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sites.id"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("assets.id"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[WorkOrderPriority] = enum_column(WorkOrderPriority, "priority", nullable=False)
    status: Mapped[WorkOrderStatus] = enum_column(WorkOrderStatus, "status", nullable=False)
    assignee_contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("contacts.id", ondelete="SET NULL"))
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Set when people were told the work order is past due, so they are told once.
    overdue_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completion_note: Mapped[str | None] = mapped_column(String(2000))


class Notification(IdMixin, TimestampMixin, TenantMixin, Base):
    """An outbox row. Delivery is retried with backoff until sent or given up."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_status_next", "status", "next_attempt_at"),)

    alert_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("contacts.id", ondelete="SET NULL"))
    channel: Mapped[Channel] = enum_column(Channel, "channel", nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NotificationStatus] = enum_column(NotificationStatus, "status", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
