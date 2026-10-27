"""State changes people make: acknowledging and resolving alerts, moving work orders.

Repeating the current state is a harmless no-op (double-clicks, retries).
An impossible move is a 409 that names the allowed moves.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import utcnow
from app.enums import AlertStatus, WorkOrderStatus
from app.errors import Conflict, ValidationFailed
from app.models import Alert, Asset, Contact, Site, WorkOrder
from app.schemas.operations import WorkOrderCreateIn, WorkOrderUpdateIn
from app.services import audit
from app.services.context import Ctx
from app.services.scoping import get_or_404

# ------------------------------------------------------------------ alerts


def acknowledge_alert(session: Session, ctx: Ctx, alert_id: uuid.UUID, note: str | None) -> Alert:
    alert = get_or_404(session, Alert, ctx.org_id, alert_id, label="Alert", for_update=True)
    if alert.status == AlertStatus.ACKNOWLEDGED:
        return alert
    if alert.status != AlertStatus.OPEN:
        raise Conflict("Only open alerts can be acknowledged. Reopen it first.", code="INVALID_TRANSITION")
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = utcnow()
    alert.acknowledged_by_user_id = ctx.actor.user_id
    session.flush()
    audit.record(session, ctx, "alert.acknowledged", "alert", alert.id, {"note": note})
    return alert


def resolve_alert(session: Session, ctx: Ctx, alert_id: uuid.UUID, note: str | None) -> Alert:
    alert = get_or_404(session, Alert, ctx.org_id, alert_id, label="Alert", for_update=True)
    if alert.status == AlertStatus.RESOLVED:
        return alert
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = utcnow()
    alert.resolved_by_user_id = ctx.actor.user_id
    alert.resolution_note = note
    session.flush()
    audit.record(session, ctx, "alert.resolved", "alert", alert.id, {"note": note})
    return alert


def reopen_alert(session: Session, ctx: Ctx, alert_id: uuid.UUID, note: str | None) -> Alert:
    alert = get_or_404(session, Alert, ctx.org_id, alert_id, label="Alert", for_update=True)
    if alert.status != AlertStatus.RESOLVED:
        raise Conflict("Only resolved alerts can be reopened.", code="INVALID_TRANSITION")
    alert.status = AlertStatus.OPEN
    alert.resolved_at = None
    alert.resolved_by_user_id = None
    alert.resolution_note = None
    alert.acknowledged_at = None
    alert.acknowledged_by_user_id = None
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        raise Conflict(
            "A newer alert for the same rule and location is already open. Use that one.",
            code="LIVE_ALERT_EXISTS",
        ) from None
    audit.record(session, ctx, "alert.reopened", "alert", alert.id, {"note": note})
    return alert


# ------------------------------------------------------------- work orders

_ALLOWED: dict[WorkOrderStatus, set[WorkOrderStatus]] = {
    WorkOrderStatus.OPEN: {WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.DONE, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.IN_PROGRESS: {WorkOrderStatus.OPEN, WorkOrderStatus.DONE, WorkOrderStatus.CANCELLED},
    WorkOrderStatus.DONE: {WorkOrderStatus.OPEN},
    WorkOrderStatus.CANCELLED: {WorkOrderStatus.OPEN},
}

_WO_FIELDS = ["title", "description", "priority", "assignee_contact_id", "due_at"]


def _check_assignee(session: Session, ctx: Ctx, contact_id: uuid.UUID | None) -> uuid.UUID | None:
    if contact_id is None:
        return None
    contact = get_or_404(session, Contact, ctx.org_id, contact_id, label="Contact")
    if not contact.is_active:
        raise ValidationFailed("That contact is deactivated.", code="CONTACT_INACTIVE")
    return contact.id


def create_work_order(session: Session, ctx: Ctx, data: WorkOrderCreateIn) -> WorkOrder:
    site_id = data.site_id
    asset_id = data.asset_id
    if data.alert_id is not None:
        alert = get_or_404(session, Alert, ctx.org_id, data.alert_id, label="Alert")
        site_id = site_id or alert.site_id
        asset_id = asset_id or alert.asset_id
    if site_id is not None:
        get_or_404(session, Site, ctx.org_id, site_id, label="Site")
    if asset_id is not None:
        asset = get_or_404(session, Asset, ctx.org_id, asset_id, label="Asset")
        if site_id is not None and asset.site_id != site_id:
            raise ValidationFailed("That asset is not at that site.", code="ASSET_NOT_AT_SITE")
        site_id = asset.site_id
    work_order = WorkOrder(
        org_id=ctx.org_id,
        alert_id=data.alert_id,
        site_id=site_id,
        asset_id=asset_id,
        title=data.title,
        description=data.description,
        priority=data.priority,
        status=WorkOrderStatus.OPEN,
        assignee_contact_id=_check_assignee(session, ctx, data.assignee_contact_id),
        due_at=data.due_at,
    )
    session.add(work_order)
    session.flush()
    audit.record(
        session,
        ctx,
        "work_order.created",
        "work_order",
        work_order.id,
        {f: getattr(work_order, f) for f in _WO_FIELDS},
    )
    return work_order


def update_work_order(session: Session, ctx: Ctx, wo_id: uuid.UUID, data: WorkOrderUpdateIn) -> WorkOrder:
    work_order = get_or_404(session, WorkOrder, ctx.org_id, wo_id, label="Work order", for_update=True)
    before = {f: getattr(work_order, f) for f in _WO_FIELDS}
    changes = data.provided()
    if changes.get("title") is not None:
        work_order.title = changes["title"]
    if "description" in changes:
        work_order.description = changes["description"]
    if changes.get("priority") is not None:
        work_order.priority = changes["priority"]
    if "assignee_contact_id" in changes:
        work_order.assignee_contact_id = _check_assignee(session, ctx, changes["assignee_contact_id"])
    if "due_at" in changes:
        work_order.due_at = changes["due_at"]
    session.flush()
    audit.record(
        session,
        ctx,
        "work_order.updated",
        "work_order",
        work_order.id,
        audit.diff(before, {f: getattr(work_order, f) for f in _WO_FIELDS}),
    )
    return work_order


def transition_work_order(
    session: Session, ctx: Ctx, wo_id: uuid.UUID, status: WorkOrderStatus, note: str | None
) -> WorkOrder:
    work_order = get_or_404(session, WorkOrder, ctx.org_id, wo_id, label="Work order", for_update=True)
    current = WorkOrderStatus(work_order.status)
    if current == status:
        return work_order
    if status not in _ALLOWED[current]:
        raise Conflict(
            f"A work order cannot go from {current} to {status}.",
            code="INVALID_TRANSITION",
            details={"allowed": sorted(s.value for s in _ALLOWED[current])},
        )
    work_order.status = status
    if status == WorkOrderStatus.DONE:
        work_order.completed_at = utcnow()
        work_order.completion_note = note
    elif current == WorkOrderStatus.DONE:
        work_order.completed_at = None
        work_order.completion_note = None
    session.flush()
    audit.record(
        session,
        ctx,
        "work_order.status_changed",
        "work_order",
        work_order.id,
        {"from": current, "to": status, "note": note},
    )
    return work_order
