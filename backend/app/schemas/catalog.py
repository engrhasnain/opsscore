"""Sites, assets, contacts, event types and rules."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import EmailStr, Field

from app.enums import EventCategory, Locale, Severity
from app.schemas.common import In, Out, Scalar, ShortText

Attributes = Annotated[dict[str, Scalar], Field(max_length=50)]


class SiteCreateIn(In):
    code: Annotated[str, Field(min_length=1, max_length=64)]
    name: ShortText
    kind: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    attributes: Attributes = Field(default_factory=dict)


class SiteUpdateIn(In):
    code: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    name: ShortText | None = None
    kind: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    attributes: Attributes | None = None
    is_active: bool | None = None


class SiteOut(Out):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    latitude: float | None
    longitude: float | None
    timezone: str | None
    attributes: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AssetCreateIn(In):
    site_id: uuid.UUID | None = None
    site_code: str | None = None
    code: Annotated[str, Field(min_length=1, max_length=64)]
    name: ShortText
    asset_type: Annotated[str, Field(min_length=1, max_length=60)]
    criticality: Annotated[int, Field(ge=1, le=5)] = 3
    attributes: Attributes = Field(default_factory=dict)


class AssetUpdateIn(In):
    site_id: uuid.UUID | None = None
    code: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    name: ShortText | None = None
    asset_type: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    criticality: Annotated[int, Field(ge=1, le=5)] | None = None
    attributes: Attributes | None = None
    is_active: bool | None = None


class AssetOut(Out):
    id: uuid.UUID
    site_id: uuid.UUID
    code: str
    name: str
    asset_type: str
    criticality: int
    attributes: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ContactCreateIn(In):
    name: ShortText
    role_label: Annotated[str, Field(max_length=80)] | None = None
    email: EmailStr | None = None
    phone: str | None = None
    whatsapp: str | None = None
    locale: Locale | None = None


class ContactUpdateIn(In):
    name: ShortText | None = None
    role_label: Annotated[str, Field(max_length=80)] | None = None
    email: EmailStr | None = None
    phone: str | None = None
    whatsapp: str | None = None
    locale: Locale | None = None
    is_active: bool | None = None


class ContactOut(Out):
    id: uuid.UUID
    name: str
    role_label: str | None
    email: str | None
    phone: str | None
    whatsapp: str | None
    locale: Locale | None
    is_active: bool
    created_at: datetime


class EventTypeCreateIn(In):
    key: Annotated[str, Field(min_length=1, max_length=64)]
    name: ShortText
    description: Annotated[str, Field(max_length=1000)] | None = None
    category: EventCategory
    default_severity: Severity = Severity.MEDIUM
    attributes_schema: list[dict[str, Any]] = Field(default_factory=list)


class EventTypeUpdateIn(In):
    name: ShortText | None = None
    description: Annotated[str, Field(max_length=1000)] | None = None
    category: EventCategory | None = None
    default_severity: Severity | None = None
    attributes_schema: list[dict[str, Any]] | None = None
    is_active: bool | None = None


class EventTypeOut(Out):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    category: EventCategory
    default_severity: Severity
    attributes_schema: list[dict[str, Any]]
    is_system: bool
    is_active: bool
    created_at: datetime


class RuleCreateIn(In):
    name: ShortText
    description: Annotated[str, Field(max_length=1000)] | None = None
    event_type: str | None = Field(default=None, description="Event type key; omit for all types")
    match: str = "all"
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    severity_override: Severity | None = None
    renotify_after_seconds: Annotated[int, Field(ge=0, le=7 * 24 * 3600)] = 0
    priority: Annotated[int, Field(ge=0, le=10_000)] = 100


class RuleUpdateIn(In):
    name: ShortText | None = None
    description: Annotated[str, Field(max_length=1000)] | None = None
    event_type: str | None = None
    match: str | None = None
    conditions: list[dict[str, Any]] | None = None
    actions: list[dict[str, Any]] | None = None
    severity_override: Severity | None = None
    renotify_after_seconds: Annotated[int, Field(ge=0, le=7 * 24 * 3600)] | None = None
    priority: Annotated[int, Field(ge=0, le=10_000)] | None = None
    is_active: bool | None = None


class RuleOut(Out):
    id: uuid.UUID
    name: str
    description: str | None
    event_type_id: uuid.UUID | None
    match: str
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    severity_override: Severity | None
    renotify_after_seconds: int
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ImportRowError(Out):
    row: int
    field: str | None
    message: str


class ImportResultOut(Out):
    dry_run: bool
    rows: int
    created: int
    updated: int
    errors: list[ImportRowError]
