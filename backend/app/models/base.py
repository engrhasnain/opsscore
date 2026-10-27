"""Shared column helpers and mixins for ORM models."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db import UTCDateTime, new_id, utcnow


def enum_column(enum_cls: type[StrEnum], name: str, **kwargs) -> Mapped:
    """A portable enum column: VARCHAR plus a CHECK constraint.

    Native PostgreSQL enums make adding a value a migration; VARCHAR + CHECK
    keeps the same safety without that cost.
    """
    return mapped_column(
        SAEnum(
            enum_cls,
            name=name,
            native_enum=False,
            create_constraint=True,
            length=32,
            validate_strings=True,
            values_callable=lambda members: [m.value for m in members],
        ),
        **kwargs,
    )


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class TenantMixin:
    """Marks a table as tenant data. Every row belongs to exactly one organization."""

    __tenant_scoped__ = True

    @declared_attr
    def org_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
