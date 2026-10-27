"""Sign-in, client onboarding, members and API keys."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.enums import ROLE_RANK, Locale, Module, Region, Role, UnitSystem
from app.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from app.models import ApiKey, Membership, Organization, User
from app.packs import apply_starter_pack, ensure_module_setup
from app.schemas.tenancy import (
    ApiKeyCreateIn,
    MemberCreateIn,
    OrgCreateIn,
    OrgUpdateIn,
    OwnerIn,
)
from app.security import (
    api_key_matches,
    burn_password_check,
    create_access_token,
    generate_api_key,
    hash_password,
    parse_api_key_prefix,
    password_problems,
    verify_password,
)
from app.services import audit
from app.services import validation as v
from app.services.context import Actor, Ctx
from app.services.scoping import get_or_404, scoped

_REGION_DEFAULTS = {
    Region.US: (Locale.EN, UnitSystem.IMPERIAL),
    Region.LATAM: (Locale.ES, UnitSystem.METRIC),
    Region.OTHER: (Locale.EN, UnitSystem.METRIC),
}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _require_strong(password: str | None) -> str:
    if not password:
        raise ValidationFailed("A password is required for a new account.")
    problems = password_problems(password)
    if problems:
        raise ValidationFailed("Password " + "; ".join(problems) + ".", code="WEAK_PASSWORD")
    return password


# ------------------------------------------------------------------ sign in


@dataclass
class LoginResult:
    token: str
    expires_in: int
    user: User
    org: Organization | None


def login(session: Session, email: str, password: str, org_slug: str | None) -> LoginResult:
    """One generic error for every failure, so attackers learn nothing."""
    invalid = Unauthorized("Invalid email or password.", code="INVALID_CREDENTIALS")
    user = session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        burn_password_check(password)
        raise invalid
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise invalid

    rows = session.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == user.id, Organization.is_active.is_(True))
        .order_by(Organization.name)
    ).all()

    org = None
    if org_slug:
        match = [o for _m, o in rows if o.slug == org_slug.strip().lower()]
        if not match:
            raise Forbidden("You do not have access to that organization.", code="NO_ACCESS")
        org = match[0]
    elif len(rows) == 1:
        org = rows[0][1]
    elif len(rows) > 1:
        raise ValidationFailed(
            "You belong to several organizations. Say which one.",
            code="ORGANIZATION_REQUIRED",
            details=[{"slug": o.slug, "name": o.name} for _m, o in rows],
        )
    elif not user.is_platform_admin:
        raise Forbidden("Your account is not linked to an active organization.", code="NO_ORGANIZATION")

    user.last_login_at = utcnow()
    ttl = get_settings().access_token_ttl_minutes * 60
    token = create_access_token(user.id, org.id if org else None, user.token_version)
    return LoginResult(token=token, expires_in=ttl, user=user, org=org)


def change_password(session: Session, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise Unauthorized("Current password is wrong.", code="INVALID_CREDENTIALS")
    if current == new:
        raise ValidationFailed("The new password must be different.")
    user.password_hash = hash_password(_require_strong(new))
    user.token_version += 1  # signs out every other session


def sign_out_everywhere(user: User) -> None:
    user.token_version += 1


@dataclass
class ApiKeyAuth:
    api_key: ApiKey
    org: Organization


def authenticate_api_key(session: Session, plaintext: str) -> ApiKeyAuth:
    invalid = Unauthorized("Invalid API key.", code="INVALID_API_KEY")
    prefix = parse_api_key_prefix(plaintext)
    if prefix is None:
        raise invalid
    api_key = session.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    if api_key is None or not api_key_matches(plaintext, api_key.key_hash):
        raise invalid
    now = utcnow()
    if api_key.revoked_at is not None or (api_key.expires_at and api_key.expires_at <= now):
        raise invalid
    org = session.get(Organization, api_key.org_id)
    if org is None or not org.is_active:
        raise Forbidden("This organization is deactivated.", code="ORG_INACTIVE")
    # Throttle the write: last_used_at is for humans, minute precision is plenty.
    if api_key.last_used_at is None or now - api_key.last_used_at > timedelta(minutes=1):
        api_key.last_used_at = now
    return ApiKeyAuth(api_key=api_key, org=org)


# ------------------------------------------------------------ organizations


def _get_or_create_owner(session: Session, owner: OwnerIn) -> User:
    user = session.scalar(select(User).where(User.email == normalize_email(owner.email)))
    if user is not None:
        return user  # existing account keeps its own password
    user = User(
        email=normalize_email(owner.email),
        full_name=owner.full_name,
        password_hash=hash_password(_require_strong(owner.password)),
    )
    session.add(user)
    session.flush()
    return user


def create_organization(session: Session, actor: Actor, data: OrgCreateIn) -> Organization:
    slug = v.slug(data.slug)
    if session.scalar(select(Organization).where(Organization.slug == slug)) is not None:
        raise Conflict(f"The slug {slug} is taken.", code="DUPLICATE_SLUG")
    locale, units = _REGION_DEFAULTS[data.region]
    modules = sorted({m.value for m in data.enabled_modules})
    org = Organization(
        name=data.name,
        slug=slug,
        industry=data.industry,
        region=data.region,
        default_locale=data.default_locale or locale,
        unit_system=data.unit_system or units,
        timezone=v.timezone(data.timezone, required=True),
        enabled_modules=modules,
    )
    session.add(org)
    session.flush()

    owner = _get_or_create_owner(session, data.owner)
    session.add(Membership(org_id=org.id, user_id=owner.id, role=Role.OWNER))
    session.flush()

    ctx = Ctx(org=org, actor=actor)
    audit.record(
        session,
        ctx,
        "organization.created",
        "organization",
        org.id,
        {
            "name": org.name,
            "slug": slug,
            "industry": org.industry,
            "region": org.region,
            "owner_user_id": owner.id,
            "modules": modules,
        },
    )
    if data.apply_starter_pack:
        created = apply_starter_pack(session, ctx, org.industry)
        audit.record(session, ctx, "organization.starter_pack_applied", "organization", org.id, created)
    ensure_module_setup(session, ctx, modules)
    return org


_ORG_FIELDS = ["name", "industry", "region", "default_locale", "unit_system", "timezone", "enabled_modules"]


def update_organization(session: Session, ctx: Ctx, data: OrgUpdateIn) -> Organization:
    org = ctx.org
    before = {f: getattr(org, f) for f in _ORG_FIELDS}
    changes = data.provided()
    for name in ("name", "industry", "region", "default_locale", "unit_system"):
        if changes.get(name) is not None:
            setattr(org, name, changes[name])
    if changes.get("timezone") is not None:
        org.timezone = v.timezone(changes["timezone"], required=True)
    if changes.get("enabled_modules") is not None:
        org.enabled_modules = sorted({Module(m).value for m in changes["enabled_modules"]})
    session.flush()
    audit.record(
        session,
        ctx,
        "organization.updated",
        "organization",
        org.id,
        audit.diff(before, {f: getattr(org, f) for f in _ORG_FIELDS}),
    )
    ensure_module_setup(session, ctx, org.enabled_modules)
    return org


# ------------------------------------------------------------------ members


def _owner_count(session: Session, org_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id == org_id, Membership.role == Role.OWNER)
        )
        or 0
    )


def _can_assign(actor_role: Role | None, target_role: Role) -> bool:
    """Admins manage roles below admin; only owners grant or touch admin and owner."""
    if actor_role == Role.OWNER:
        return True
    return actor_role == Role.ADMIN and ROLE_RANK[target_role] < ROLE_RANK[Role.ADMIN]


def add_member(session: Session, ctx: Ctx, data: MemberCreateIn) -> Membership:
    """Add a person by email.

    Whether the email already has an account (perhaps at another client) must not
    show: the same inputs are required either way (a strong password), and the
    API answers with what the admin typed, never the stored account's details.
    """
    if not _can_assign(ctx.role, data.role):
        raise Forbidden(f"Your role cannot grant the {data.role} role.", code="ROLE_TOO_HIGH")
    password = _require_strong(data.password)
    email = normalize_email(data.email)
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, full_name=data.full_name, password_hash=hash_password(password))
        session.add(user)
        session.flush()
    elif session.scalar(scoped(Membership, ctx.org_id).where(Membership.user_id == user.id)):
        raise Conflict("That person is already a member.", code="ALREADY_MEMBER")
    else:
        burn_password_check(password)  # same work as hashing a new password, so timing tells nothing
    # An existing account is linked as-is; this org cannot reset its password or rename it.
    membership = Membership(org_id=ctx.org_id, user_id=user.id, role=data.role)
    session.add(membership)
    session.flush()
    audit.record(
        session,
        ctx,
        "member.added",
        "membership",
        membership.id,
        {"user_id": user.id, "email": email, "role": data.role},
    )
    return membership


def change_member_role(session: Session, ctx: Ctx, membership_id: uuid.UUID, role: Role) -> Membership:
    membership = get_or_404(session, Membership, ctx.org_id, membership_id, label="Member", for_update=True)
    if membership.role == role:
        return membership
    if not (_can_assign(ctx.role, membership.role) and _can_assign(ctx.role, role)):
        raise Forbidden("Your role cannot make this change.", code="ROLE_TOO_HIGH")
    if membership.role == Role.OWNER and _owner_count(session, ctx.org_id) <= 1:
        raise Conflict("An organization must keep at least one owner.", code="LAST_OWNER")
    previous = membership.role
    membership.role = role
    session.flush()
    audit.record(
        session,
        ctx,
        "member.role_changed",
        "membership",
        membership.id,
        {"user_id": membership.user_id, "from": previous, "to": role},
    )
    return membership


def remove_member(session: Session, ctx: Ctx, membership_id: uuid.UUID) -> None:
    membership = get_or_404(session, Membership, ctx.org_id, membership_id, label="Member", for_update=True)
    if not _can_assign(ctx.role, membership.role) and membership.user_id != ctx.actor.user_id:
        raise Forbidden("Your role cannot remove this member.", code="ROLE_TOO_HIGH")
    if membership.role == Role.OWNER and _owner_count(session, ctx.org_id) <= 1:
        raise Conflict("An organization must keep at least one owner.", code="LAST_OWNER")
    audit.record(
        session,
        ctx,
        "member.removed",
        "membership",
        membership.id,
        {"user_id": membership.user_id, "role": membership.role},
    )
    session.delete(membership)
    session.flush()


# ----------------------------------------------------------------- api keys


def create_api_key(session: Session, ctx: Ctx, data: ApiKeyCreateIn) -> tuple[ApiKey, str]:
    if data.expires_at is not None and data.expires_at <= utcnow():
        raise ValidationFailed("expires_at must be in the future.")
    generated = generate_api_key()
    api_key = ApiKey(
        org_id=ctx.org_id,
        name=data.name,
        prefix=generated.prefix,
        key_hash=generated.key_hash,
        scopes=sorted({s.value for s in data.scopes}),
        expires_at=data.expires_at,
        created_by_user_id=ctx.actor.user_id,
    )
    session.add(api_key)
    session.flush()
    audit.record(
        session,
        ctx,
        "api_key.created",
        "api_key",
        api_key.id,
        {"name": api_key.name, "prefix": api_key.prefix, "scopes": api_key.scopes, "expires_at": api_key.expires_at},
    )
    return api_key, generated.plaintext


def revoke_api_key(session: Session, ctx: Ctx, key_id: uuid.UUID) -> ApiKey:
    api_key = get_or_404(session, ApiKey, ctx.org_id, key_id, label="API key", for_update=True)
    if api_key.revoked_at is None:
        api_key.revoked_at = utcnow()
        session.flush()
        audit.record(session, ctx, "api_key.revoked", "api_key", api_key.id, {"prefix": api_key.prefix})
    return api_key


def membership_for(session: Session, user_id: uuid.UUID, org_id: uuid.UUID) -> Membership:
    membership = session.scalar(scoped(Membership, org_id).where(Membership.user_id == user_id))
    if membership is None:
        raise NotFound("Membership not found.")
    return membership
