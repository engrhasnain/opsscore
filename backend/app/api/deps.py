"""Request dependencies: database session, authentication, permissions, paging."""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import BYPASS_KEY, get_session_factory, set_tenant
from app.enums import Module, Role
from app.errors import Forbidden, Unauthorized
from app.models import ApiKey, Membership, Organization, User
from app.security import decode_access_token
from app.services import tenancy
from app.services.context import Actor, Ctx
from app.services.permissions import Permission, role_allows, scopes_allow
from app.services.scoping import MAX_PAGE_SIZE

_bearer = HTTPBearer(auto_error=False, description="User access token or API key")


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DB = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    user: User | None = None
    api_key: ApiKey | None = None
    org: Organization | None = None
    role: Role | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def actor(self) -> Actor:
        if self.api_key is not None:
            return Actor.for_api_key(self.api_key.id)
        assert self.user is not None
        return Actor.for_user(self.user.id)


def _user_principal(session: Session, token: str) -> Principal:
    invalid = Unauthorized("Your session has expired or is not valid. Sign in again.")
    claims = decode_access_token(token)
    if claims is None:
        raise invalid
    user = session.get(User, claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.token_version:
        raise invalid
    if claims.org_id is None:
        return Principal(user=user)
    org = session.get(Organization, claims.org_id)
    if org is None or not org.is_active:
        raise Forbidden("This organization is deactivated.", code="ORG_INACTIVE")
    membership = session.query(Membership).filter_by(org_id=org.id, user_id=user.id).one_or_none()
    if membership is None:
        raise Forbidden("You no longer have access to this organization.", code="NO_ACCESS")
    return Principal(user=user, org=org, role=Role(membership.role))


def get_principal(
    request: Request,
    session: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    api_key_header = request.headers.get("x-api-key")
    token = credentials.credentials if credentials else None
    if not token and not api_key_header:
        raise Unauthorized("Sign in, or send an API key.")

    # Credentials are looked up across tenants; everything after runs inside one.
    session.info[BYPASS_KEY] = True
    secret = api_key_header or token
    if secret and secret.startswith("ok_"):
        auth = tenancy.authenticate_api_key(session, secret)
        principal = Principal(api_key=auth.api_key, org=auth.org, scopes=frozenset(auth.api_key.scopes))
    else:
        principal = _user_principal(session, token or "")
    set_tenant(session, principal.org.id if principal.org else None)
    request.state.principal = principal
    return principal


def require(permission: Permission, *, module: Module | None = None) -> Callable[..., Ctx]:
    """Dependency: the caller must hold ``permission`` inside an organization."""

    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Ctx:
        if principal.org is None:
            raise Forbidden("Sign in to an organization first.", code="NO_ORGANIZATION")
        if principal.api_key is not None:
            allowed = scopes_allow(principal.scopes, permission)
        else:
            allowed = role_allows(principal.role, permission)
        if not allowed:
            raise Forbidden("You do not have permission to do this.", code="PERMISSION_DENIED")
        if module is not None and module.value not in principal.org.enabled_modules:
            raise Forbidden(f"The {module.value} module is not enabled.", code="MODULE_NOT_ENABLED")
        return Ctx(org=principal.org, actor=principal.actor, role=principal.role, scopes=principal.scopes)

    return dependency


def require_user(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if principal.user is None:
        raise Forbidden("This needs a signed-in person, not an API key.", code="USER_REQUIRED")
    return principal


def require_platform_admin(principal: Annotated[Principal, Depends(require_user)]) -> Principal:
    if not principal.user.is_platform_admin:
        raise Forbidden("Platform administrators only.", code="PERMISSION_DENIED")
    return principal


@dataclass
class Paging:
    limit: int
    offset: int


def paging(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> Paging:
    return Paging(limit=limit, offset=offset)


PageParams = Annotated[Paging, Depends(paging)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
