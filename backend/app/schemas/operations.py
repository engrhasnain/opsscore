"""Events, alerts, work orders, notifications and the audit log."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import AwareDatetime, Field

from app.enums import (
    ActorType,
    AlertStatus,
    Channel,
    NotificationStatus,
    Severity,
    WorkOrderPriority,
    WorkOrderStatus,
)
from app.schemas.common import In, Out


class EventIn(In):
    event_type: Annotated[str, Field(min_length=1, max_length=64, description="Event type key")]
    site_id: uuid.UUID | None = None
    site_code: Annotated[str, Field(max_length=64)] | None = None
    asset_id: uuid.UUID | None = None
    asset_code: Annotated[str, Field(max_length=64)] | None = None
    occurred_at: AwareDatetime | None = Field(
        default=None, description="When it happened, with a UTC offset. Defaults to now."
    )
    severity: Severity | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    description: Annotated[str, Field(max_length=2000)] | None = None
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)] | None = Field(
        default=None, description="Resending with the same key returns the original event."
    )


class EventOut(Out):
    id: uuid.UUID
    event_type_id: uuid.UUID
    site_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    severity: Severity
    occurred_at: datetime
    received_at: datetime
    attributes: dict[str, Any]
    description: str | None
    source_type: ActorType
    source_id: str | None
    idempotency_key: str | None


class AlertOutcomeOut(Out):
    alert_id: uuid.UUID
    rule_id: uuid.UUID
    outcome: str
    severity: Severity
    notifications: int
    work_order_id: uuid.UUID | None = None


class IngestOut(Out):
    event: EventOut
    created: bool
    alerts: list[AlertOutcomeOut]
    warnings: list[str]


class RuleTestIn(In):
    event: EventIn


class RuleTestOut(Out):
    matched: bool
    severity: Severity | None
    recipients: list[dict[str, Any]]
    work_order_title: str | None
    warnings: list[str]


class AlertOut(Out):
    id: uuid.UUID
    rule_id: uuid.UUID
    first_event_id: uuid.UUID
    site_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    title: str
    severity: Severity
    status: AlertStatus
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    last_notified_at: datetime | None
    acknowledged_by_user_id: uuid.UUID | None
    acknowledged_at: datetime | None
    resolved_by_user_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime


class AlertDetailOut(AlertOut):
    events: list[EventOut]


class AlertActionIn(In):
    note: Annotated[str, Field(max_length=2000)] | None = None


class WorkOrderCreateIn(In):
    title: Annotated[str, Field(min_length=1, max_length=300)]
    description: Annotated[str, Field(max_length=4000)] | None = None
    priority: WorkOrderPriority = WorkOrderPriority.NORMAL
    alert_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    assignee_contact_id: uuid.UUID | None = None
    due_at: AwareDatetime | None = None


class WorkOrderUpdateIn(In):
    title: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    description: Annotated[str, Field(max_length=4000)] | None = None
    priority: WorkOrderPriority | None = None
    assignee_contact_id: uuid.UUID | None = None
    due_at: AwareDatetime | None = None


class WorkOrderTransitionIn(In):
    status: WorkOrderStatus
    note: Annotated[str, Field(max_length=2000)] | None = None


class WorkOrderOut(Out):
    id: uuid.UUID
    alert_id: uuid.UUID | None
    site_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    title: str
    description: str | None
    priority: WorkOrderPriority
    status: WorkOrderStatus
    assignee_contact_id: uuid.UUID | None
    due_at: datetime | None
    completed_at: datetime | None
    completion_note: str | None
    created_at: datetime
    updated_at: datetime


class NotificationOut(Out):
    id: uuid.UUID
    alert_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    channel: Channel
    recipient: str | None
    subject: str
    status: NotificationStatus
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime


class DispatchOut(Out):
    attempted: int
    sent: int
    failed: int
    retrying: int


class AuditEntryOut(Out):
    id: uuid.UUID
    seq: int
    created_at: datetime
    actor_type: ActorType
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    changes: dict[str, Any]
    request_id: str | None
    hash: str


class ChainReportOut(Out):
    valid: bool
    entries_checked: int
    first_invalid_seq: int | None
    reason: str | None
