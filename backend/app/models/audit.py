"""Tamper-evident audit log."""

from datetime import datetime

from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, JSONType, UTCDateTime
from app.enums import ActorType
from app.models.base import IdMixin, TenantMixin, enum_column


class AuditEntry(IdMixin, TenantMixin, Base):
    """One recorded action. Entries are hash-chained per organization.

    Each entry stores the hash of the previous one, so editing or deleting any
    row breaks every hash after it, and ``/audit/verify`` reports where.
    """

    __tablename__ = "audit_entries"
    __table_args__ = (
        UniqueConstraint("org_id", "seq"),
        Index("ix_audit_entity", "org_id", "entity_type", "entity_id"),
    )

    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actor_type: Mapped[ActorType] = enum_column(ActorType, "actor_type", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    changes: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
