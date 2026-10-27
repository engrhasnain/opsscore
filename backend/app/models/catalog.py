"""What a client configures: sites, assets, contacts and event types."""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, JSONType
from app.enums import EventCategory, Locale, Severity
from app.models.base import IdMixin, TenantMixin, TimestampMixin, enum_column


class Site(IdMixin, TimestampMixin, TenantMixin, Base):
    """A physical place: well pad, plant, terminal, gate, yard, berth."""

    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("org_id", "code"),
        CheckConstraint("latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", "lat_range"),
        CheckConstraint("longitude IS NULL OR (longitude >= -180 AND longitude <= 180)", "lon_range"),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="site")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    timezone: Mapped[str | None] = mapped_column(String(64))
    attributes: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Asset(IdMixin, TimestampMixin, TenantMixin, Base):
    """A piece of equipment at a site: compressor, tank, crane, gate, vehicle."""

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("org_id", "code"),
        CheckConstraint("criticality >= 1 AND criticality <= 5", "criticality_range"),
    )

    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(60), nullable=False)
    criticality: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    attributes: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Contact(IdMixin, TimestampMixin, TenantMixin, Base):
    """Someone who receives alerts. Not necessarily a user who can sign in."""

    __tablename__ = "contacts"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_label: Mapped[str | None] = mapped_column(String(80), index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(20))
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    locale: Mapped[Locale | None] = enum_column(Locale, "contact_locale")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EventType(IdMixin, TimestampMixin, TenantMixin, Base):
    """A kind of thing that can happen, defined by the client.

    ``attributes_schema`` lists the fields an event of this type may carry, so
    bad data from a device is rejected at the door instead of breaking a rule
    later. ``is_system`` types are created by the platform and cannot be removed.
    """

    __tablename__ = "event_types"
    __table_args__ = (UniqueConstraint("org_id", "key"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    category: Mapped[EventCategory] = enum_column(EventCategory, "category", nullable=False)
    default_severity: Mapped[Severity] = enum_column(Severity, "default_severity", nullable=False)
    attributes_schema: Mapped[list[dict]] = mapped_column(JSONType, nullable=False, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
