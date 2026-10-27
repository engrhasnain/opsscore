"""Sign in, who am I, password, sign out everywhere."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select

from app.api.deps import DB, Principal, client_ip, require_user
from app.db import set_tenant
from app.models import Membership, Organization
from app.schemas.tenancy import (
    LoginIn,
    MembershipSummary,
    MeOut,
    OrgSummary,
    PasswordChangeIn,
    TokenOut,
    UserOut,
)
from app.services import tenancy

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, session: DB) -> TokenOut:
    limiter = request.app.state.login_limiter
    email = tenancy.normalize_email(body.email)
    limiter.hit(f"email:{email}")
    limiter.hit(f"ip:{client_ip(request)}")
    # Sign-in looks up the person's memberships across every client, before any tenant
    # is chosen; with PostgreSQL row-level security that lookup needs the bypass.
    set_tenant(session, None, bypass=True)
    result = tenancy.login(session, email, body.password, body.organization)
    session.commit()
    return TokenOut(
        access_token=result.token,
        expires_in=result.expires_in,
        organization=OrgSummary.model_validate(result.org) if result.org else None,
    )


@router.get("/me", response_model=MeOut)
def me(principal: Annotated[Principal, Depends(require_user)], session: DB) -> MeOut:
    # The person's own memberships in every client (filtered by user below), not just this one.
    set_tenant(session, None, bypass=True)
    rows = session.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == principal.user.id, Organization.is_active.is_(True))
        .order_by(Organization.name)
    ).all()
    return MeOut(
        user=UserOut.model_validate(principal.user),
        organization=OrgSummary.model_validate(principal.org) if principal.org else None,
        role=principal.role,
        memberships=[MembershipSummary(organization=OrgSummary.model_validate(o), role=m.role) for m, o in rows],
    )


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeIn, principal: Annotated[Principal, Depends(require_user)], session: DB
) -> None:
    tenancy.change_password(session, principal.user, body.current_password, body.new_password)
    session.commit()


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(principal: Annotated[Principal, Depends(require_user)], session: DB) -> None:
    tenancy.sign_out_everywhere(principal.user)
    session.commit()
