"""Events in, alerts and work orders out, notifications and the audit trail."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Response, status
from pydantic import AwareDatetime
from sqlalchemy import select

from app.api.deps import DB, PageParams, require
from app.config import get_settings
from app.enums import AlertStatus, NotificationStatus, Severity, WorkOrderStatus
from app.errors import ValidationFailed
from app.models import Alert, AlertEvent, AuditEntry, Event, Notification, WorkOrder
from app.notify.dispatcher import deliver_pending
from app.schemas.common import Page
from app.schemas.operations import (
    AlertActionIn,
    AlertDetailOut,
    AlertOut,
    AlertOutcomeOut,
    AuditEntryOut,
    ChainReportOut,
    DispatchOut,
    EventIn,
    EventOut,
    IngestOut,
    NotificationOut,
    WorkOrderCreateIn,
    WorkOrderOut,
    WorkOrderTransitionIn,
    WorkOrderUpdateIn,
)
from app.services import audit, events, workflow
from app.services.context import Ctx
from app.services.permissions import Permission
from app.services.scoping import get_or_404, paginate, scoped

router = APIRouter(tags=["operations"])

Reader = Annotated[Ctx, Depends(require(Permission.READ))]
EventReader = Annotated[Ctx, Depends(require(Permission.EVENTS_READ))]
EventWriter = Annotated[Ctx, Depends(require(Permission.EVENTS_CREATE))]
AlertManager = Annotated[Ctx, Depends(require(Permission.ALERTS_MANAGE))]
WorkOrderManager = Annotated[Ctx, Depends(require(Permission.WORK_ORDERS_MANAGE))]
WorkOrderUpdater = Annotated[Ctx, Depends(require(Permission.WORK_ORDERS_UPDATE))]
Configurer = Annotated[Ctx, Depends(require(Permission.CONFIGURE))]
Auditor = Annotated[Ctx, Depends(require(Permission.AUDIT_READ))]


def schedule_delivery(background: BackgroundTasks, ids: list[uuid.UUID]) -> None:
    """Send right after the response, so the caller is never kept waiting on SMS."""
    if ids and get_settings().notify_inline:
        background.add_task(deliver_pending, ids=ids)


def _page(session, stmt, page) -> Page:
    items, total = paginate(session, stmt, limit=page.limit, offset=page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


def _time_window(stmt, column, since: datetime | None, until: datetime | None):
    if since and until and since > until:
        raise ValidationFailed("'since' must be before 'until'.")
    if since:
        stmt = stmt.where(column >= since)
    if until:
        stmt = stmt.where(column < until)
    return stmt


# ------------------------------------------------------------------ events


@router.post("/events", response_model=IngestOut, status_code=status.HTTP_201_CREATED)
def ingest_event(
    body: EventIn,
    ctx: EventWriter,
    session: DB,
    response: Response,
    background: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> IngestOut:
    result = events.ingest(session, ctx, body, idempotency_key=idempotency_key)
    session.commit()
    if not result.created:
        response.status_code = status.HTTP_200_OK
    schedule_delivery(background, result.pending_notification_ids)
    return IngestOut(
        event=EventOut.model_validate(result.event),
        created=result.created,
        warnings=result.warnings,
        alerts=[
            AlertOutcomeOut(
                alert_id=o.alert.id,
                rule_id=o.rule.id,
                outcome=o.outcome,
                severity=o.alert.severity,
                notifications=len(o.notifications),
                work_order_id=o.work_order.id if o.work_order else None,
            )
            for o in result.outcomes
        ],
    )


@router.get("/events", response_model=Page[EventOut])
def list_events(
    ctx: EventReader,
    session: DB,
    page: PageParams,
    site_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    event_type_id: uuid.UUID | None = None,
    severity: Severity | None = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
):
    stmt = scoped(Event, ctx.org_id).order_by(Event.occurred_at.desc())
    for column, value in (
        (Event.site_id, site_id),
        (Event.asset_id, asset_id),
        (Event.event_type_id, event_type_id),
        (Event.severity, severity),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    return _page(session, _time_window(stmt, Event.occurred_at, since, until), page)


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: uuid.UUID, ctx: EventReader, session: DB):
    return events.get_event(session, ctx, event_id)


# ------------------------------------------------------------------ alerts


@router.get("/alerts", response_model=Page[AlertOut])
def list_alerts(
    ctx: Reader,
    session: DB,
    page: PageParams,
    alert_status: Annotated[list[AlertStatus] | None, Query(alias="status")] = None,
    severity: Severity | None = None,
    site_id: uuid.UUID | None = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
):
    stmt = scoped(Alert, ctx.org_id).order_by(Alert.last_seen_at.desc())
    if alert_status:
        stmt = stmt.where(Alert.status.in_(alert_status))
    if severity is not None:
        stmt = stmt.where(Alert.severity == severity)
    if site_id is not None:
        stmt = stmt.where(Alert.site_id == site_id)
    return _page(session, _time_window(stmt, Alert.last_seen_at, since, until), page)


@router.get("/alerts/{alert_id}", response_model=AlertDetailOut)
def get_alert(alert_id: uuid.UUID, ctx: Reader, session: DB):
    alert = get_or_404(session, Alert, ctx.org_id, alert_id, label="Alert")
    linked = session.scalars(
        select(Event)
        .join(AlertEvent, AlertEvent.event_id == Event.id)
        .where(AlertEvent.alert_id == alert.id, Event.org_id == ctx.org_id)
        .order_by(Event.occurred_at)
        .limit(500)
    )
    return AlertDetailOut(**AlertOut.model_validate(alert).model_dump(), events=list(linked))


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(alert_id: uuid.UUID, ctx: AlertManager, session: DB, body: AlertActionIn | None = None):
    alert = workflow.acknowledge_alert(session, ctx, alert_id, body.note if body else None)
    session.commit()
    return alert


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: uuid.UUID, ctx: AlertManager, session: DB, body: AlertActionIn | None = None):
    alert = workflow.resolve_alert(session, ctx, alert_id, body.note if body else None)
    session.commit()
    return alert


@router.post("/alerts/{alert_id}/reopen", response_model=AlertOut)
def reopen_alert(alert_id: uuid.UUID, ctx: AlertManager, session: DB, body: AlertActionIn | None = None):
    alert = workflow.reopen_alert(session, ctx, alert_id, body.note if body else None)
    session.commit()
    return alert


# ------------------------------------------------------------- work orders


@router.get("/work-orders", response_model=Page[WorkOrderOut])
def list_work_orders(
    ctx: Reader,
    session: DB,
    page: PageParams,
    wo_status: Annotated[list[WorkOrderStatus] | None, Query(alias="status")] = None,
    assignee_contact_id: uuid.UUID | None = None,
    alert_id: uuid.UUID | None = None,
):
    stmt = scoped(WorkOrder, ctx.org_id).order_by(WorkOrder.created_at.desc())
    if wo_status:
        stmt = stmt.where(WorkOrder.status.in_(wo_status))
    if assignee_contact_id is not None:
        stmt = stmt.where(WorkOrder.assignee_contact_id == assignee_contact_id)
    if alert_id is not None:
        stmt = stmt.where(WorkOrder.alert_id == alert_id)
    return _page(session, stmt, page)


@router.post("/work-orders", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
def create_work_order(body: WorkOrderCreateIn, ctx: WorkOrderManager, session: DB):
    work_order = workflow.create_work_order(session, ctx, body)
    session.commit()
    return work_order


@router.get("/work-orders/{wo_id}", response_model=WorkOrderOut)
def get_work_order(wo_id: uuid.UUID, ctx: Reader, session: DB):
    return get_or_404(session, WorkOrder, ctx.org_id, wo_id, label="Work order")


@router.patch("/work-orders/{wo_id}", response_model=WorkOrderOut)
def update_work_order(wo_id: uuid.UUID, body: WorkOrderUpdateIn, ctx: WorkOrderManager, session: DB):
    work_order = workflow.update_work_order(session, ctx, wo_id, body)
    session.commit()
    return work_order


@router.post("/work-orders/{wo_id}/transition", response_model=WorkOrderOut)
def transition_work_order(wo_id: uuid.UUID, body: WorkOrderTransitionIn, ctx: WorkOrderUpdater, session: DB):
    work_order = workflow.transition_work_order(session, ctx, wo_id, body.status, body.note)
    session.commit()
    return work_order


# ----------------------------------------------------------- notifications


@router.get("/notifications", response_model=Page[NotificationOut])
def list_notifications(
    ctx: Reader,
    session: DB,
    page: PageParams,
    n_status: Annotated[NotificationStatus | None, Query(alias="status")] = None,
    alert_id: uuid.UUID | None = None,
):
    stmt = scoped(Notification, ctx.org_id).order_by(Notification.created_at.desc())
    if n_status is not None:
        stmt = stmt.where(Notification.status == n_status)
    if alert_id is not None:
        stmt = stmt.where(Notification.alert_id == alert_id)
    return _page(session, stmt, page)


@router.post("/notifications/dispatch", response_model=DispatchOut)
def dispatch_notifications(ctx: Configurer, session: DB):
    """Retry due notifications for this organization now, instead of waiting for the worker."""
    session.commit()
    stats = deliver_pending(org_id=ctx.org_id)
    return DispatchOut(**stats.__dict__)


# ------------------------------------------------------------------- audit


@router.get("/audit", response_model=Page[AuditEntryOut])
def list_audit(
    ctx: Auditor,
    session: DB,
    page: PageParams,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
):
    stmt = scoped(AuditEntry, ctx.org_id).order_by(AuditEntry.seq.desc())
    if entity_type:
        stmt = stmt.where(AuditEntry.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditEntry.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditEntry.action == action)
    return _page(session, stmt, page)


@router.get("/audit/verify", response_model=ChainReportOut)
def verify_audit(ctx: Auditor, session: DB):
    """Recompute the hash chain and report the first entry that does not match."""
    return audit.verify_chain(session, ctx.org_id)
