"""Platform onboarding, organization settings, members and API keys."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from app.api.deps import DB, PageParams, Principal, require, require_platform_admin
from app.db import set_tenant
from app.models import ApiKey, Membership, Organization, User
from app.schemas.common import Page
from app.schemas.tenancy import (
    ApiKeyCreatedOut,
    ApiKeyCreateIn,
    ApiKeyOut,
    MemberCreateIn,
    MemberOut,
    MemberUpdateIn,
    OrgCreateIn,
    OrgOut,
    OrgUpdateIn,
)
from app.services import tenancy
from app.services.context import Ctx
from app.services.permissions import Permission
from app.services.scoping import paginate, scoped

platform = APIRouter(prefix="/platform", tags=["platform"])
router = APIRouter(tags=["organization"])

Reader = Annotated[Ctx, Depends(require(Permission.READ))]
Settings = Annotated[Ctx, Depends(require(Permission.ORG_SETTINGS))]
MemberAdmin = Annotated[Ctx, Depends(require(Permission.MEMBERS_MANAGE))]
Configurer = Annotated[Ctx, Depends(require(Permission.CONFIGURE))]


# --------------------------------------------------------------- platform


@platform.post("/organizations", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    body: OrgCreateIn, principal: Annotated[Principal, Depends(require_platform_admin)], session: DB
) -> Organization:
    set_tenant(session, None, bypass=True)  # onboarding writes a brand-new tenant
    org = tenancy.create_organization(session, principal.actor, body)
    session.commit()
    return org


@platform.get("/organizations", response_model=Page[OrgOut])
def list_organizations(
    _admin: Annotated[Principal, Depends(require_platform_admin)], session: DB, page: PageParams
) -> Page[OrgOut]:
    set_tenant(session, None, bypass=True)
    items, total = paginate(
        session, select(Organization).order_by(Organization.name), limit=page.limit, offset=page.offset
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


# ------------------------------------------------------------- settings


@router.get("/organization", response_model=OrgOut)
def get_organization(ctx: Reader) -> Organization:
    return ctx.org


@router.patch("/organization", response_model=OrgOut)
def update_organization(body: OrgUpdateIn, ctx: Settings, session: DB) -> Organization:
    org = tenancy.update_organization(session, ctx, body)
    session.commit()
    return org


# -------------------------------------------------------------- members


def _member_out(membership: Membership, user: User) -> MemberOut:
    return MemberOut(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        is_active=user.is_active,
        created_at=membership.created_at,
    )


@router.get("/members", response_model=Page[MemberOut])
def list_members(ctx: Reader, session: DB, page: PageParams) -> Page[MemberOut]:
    stmt = (
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == ctx.org_id)
        .order_by(User.full_name)
    )
    total = session.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == ctx.org_id))
    rows = session.execute(stmt.limit(page.limit).offset(page.offset)).all()
    return Page(items=[_member_out(m, u) for m, u in rows], total=total, limit=page.limit, offset=page.offset)


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(body: MemberCreateIn, ctx: MemberAdmin, session: DB) -> MemberOut:
    membership = tenancy.add_member(session, ctx, body)
    session.commit()
    # Echo what the admin typed: an account that already existed (maybe at another
    # client) must look exactly like a new one, so its stored name never leaks.
    return MemberOut(
        id=membership.id,
        user_id=membership.user_id,
        email=tenancy.normalize_email(body.email),
        full_name=body.full_name,
        role=membership.role,
        is_active=True,
        created_at=membership.created_at,
    )


@router.patch("/members/{membership_id}", response_model=MemberOut)
def change_role(membership_id: uuid.UUID, body: MemberUpdateIn, ctx: MemberAdmin, session: DB) -> MemberOut:
    membership = tenancy.change_member_role(session, ctx, membership_id, body.role)
    session.commit()
    return _member_out(membership, session.get(User, membership.user_id))


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(membership_id: uuid.UUID, ctx: MemberAdmin, session: DB) -> None:
    tenancy.remove_member(session, ctx, membership_id)
    session.commit()


# ------------------------------------------------------------- api keys


@router.get("/api-keys", response_model=Page[ApiKeyOut])
def list_api_keys(ctx: Configurer, session: DB, page: PageParams) -> Page[ApiKeyOut]:
    stmt = scoped(ApiKey, ctx.org_id).order_by(ApiKey.created_at.desc())
    items, total = paginate(session, stmt, limit=page.limit, offset=page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("/api-keys", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_api_key(body: ApiKeyCreateIn, ctx: Configurer, session: DB) -> ApiKeyCreatedOut:
    api_key, plaintext = tenancy.create_api_key(session, ctx, body)
    session.commit()
    return ApiKeyCreatedOut(**ApiKeyOut.model_validate(api_key).model_dump(), key=plaintext)


@router.delete("/api-keys/{key_id}", response_model=ApiKeyOut)
def revoke_api_key(key_id: uuid.UUID, ctx: Configurer, session: DB) -> ApiKey:
    api_key = tenancy.revoke_api_key(session, ctx, key_id)
    session.commit()
    return api_key
