"""Organizations (clients), users, memberships and API keys."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType, UTCDateTime
from app.enums import Industry, Locale, Region, Role, UnitSystem
from app.models.base import IdMixin, TenantMixin, TimestampMixin, enum_column


class Organization(IdMixin, TimestampMixin, Base):
    """One client. Everything else in the system hangs off an organization."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    industry: Mapped[Industry] = enum_column(Industry, "industry", nullable=False)
    region: Mapped[Region] = enum_column(Region, "region", nullable=False)
    default_locale: Mapped[Locale] = enum_column(Locale, "default_locale", nullable=False)
    unit_system: Mapped[UnitSystem] = enum_column(UnitSystem, "unit_system", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    enabled_modules: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Head of the tamper-evident audit chain. Locked while appending.
    audit_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audit_head_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class User(IdMixin, TimestampMixin, Base):
    """A person who can sign in. Users are global; access comes from memberships."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Bumped to invalidate every token issued before (password change, sign out everywhere).
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Membership(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[Role] = enum_column(Role, "role", nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")


class ApiKey(IdMixin, TimestampMixin, TenantMixin, Base):
    """Machine credentials for devices and integrations (drones, sensors, WhatsApp)."""

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
