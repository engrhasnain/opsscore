"""Authentication, organizations, members and API keys."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, EmailStr, Field

from app.enums import ApiKeyScope, Industry, Locale, Module, Region, Role, UnitSystem
from app.schemas.common import In, Out, ShortText


class LoginIn(In):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=256)]
    organization: str | None = Field(default=None, description="Organization slug")


class OrgSummary(Out):
    id: uuid.UUID
    slug: str
    name: str


class TokenOut(Out):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    organization: OrgSummary | None


class UserOut(Out):
    id: uuid.UUID
    email: str
    full_name: str
    is_platform_admin: bool


class MembershipSummary(Out):
    organization: OrgSummary
    role: Role


class MeOut(Out):
    user: UserOut
    organization: OrgSummary | None
    role: Role | None
    memberships: list[MembershipSummary]


class PasswordChangeIn(In):
    current_password: Annotated[str, Field(min_length=1, max_length=256)]
    new_password: Annotated[str, Field(min_length=1, max_length=256)]


class OwnerIn(In):
    email: EmailStr
    full_name: ShortText
    password: Annotated[str, Field(max_length=256)] | None = None


class OrgCreateIn(In):
    name: ShortText
    slug: Annotated[str, Field(min_length=1, max_length=63)]
    industry: Industry
    region: Region
    default_locale: Locale | None = None
    unit_system: UnitSystem | None = None
    timezone: str
    enabled_modules: list[Module] = Field(default_factory=list)
    apply_starter_pack: bool = True
    owner: OwnerIn


class OrgUpdateIn(In):
    name: ShortText | None = None
    industry: Industry | None = None
    region: Region | None = None
    default_locale: Locale | None = None
    unit_system: UnitSystem | None = None
    timezone: str | None = None
    enabled_modules: list[Module] | None = None


class OrgOut(Out):
    id: uuid.UUID
    name: str
    slug: str
    industry: Industry
    region: Region
    default_locale: Locale
    unit_system: UnitSystem
    timezone: str
    enabled_modules: list[str]
    is_active: bool
    created_at: datetime


class MemberCreateIn(In):
    email: EmailStr
    full_name: ShortText
    role: Role
    password: Annotated[str, Field(max_length=256)] | None = Field(
        default=None, description="Required only when the person has no account yet."
    )


class MemberUpdateIn(In):
    role: Role


class MemberOut(Out):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class ApiKeyCreateIn(In):
    name: ShortText
    scopes: Annotated[list[ApiKeyScope], Field(min_length=1)]
    expires_at: AwareDatetime | None = None


class ApiKeyOut(Out):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    key: str = Field(description="Shown once. Store it now; it cannot be retrieved again.")
