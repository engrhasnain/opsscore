"""Tenant-scoped query helpers. Every read of tenant data goes through these."""

import uuid
from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.errors import NotFound

T = TypeVar("T")

MAX_PAGE_SIZE = 200


def scoped(model: type[T], org_id: uuid.UUID) -> Select:
    return select(model).where(model.org_id == org_id)


def get_or_404(
    session: Session,
    model: type[T],
    org_id: uuid.UUID,
    obj_id: uuid.UUID,
    *,
    label: str,
    for_update: bool = False,
) -> T:
    """Fetch by id inside the tenant.

    A row that belongs to another tenant is reported as *not found*, never
    *forbidden*, so ids cannot be used to probe other clients' data.
    """
    stmt = scoped(model, org_id).where(model.id == obj_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    obj = session.scalar(stmt)
    if obj is None:
        raise NotFound(f"{label} not found.")
    return obj


def paginate(session: Session, stmt: Select, *, limit: int, offset: int) -> tuple[list, int]:
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = list(session.scalars(stmt.limit(limit).offset(offset)))
    return items, int(total or 0)
