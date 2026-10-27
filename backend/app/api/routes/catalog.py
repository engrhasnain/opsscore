"""Sites, assets, contacts, event types and rules, plus CSV import."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import or_

from app.api.deps import DB, PageParams, require
from app.config import get_settings
from app.errors import PayloadTooLarge, ValidationFailed
from app.models import Asset, Contact, EventType, Rule, Site
from app.schemas.catalog import (
    AssetCreateIn,
    AssetOut,
    AssetUpdateIn,
    ContactCreateIn,
    ContactOut,
    ContactUpdateIn,
    EventTypeCreateIn,
    EventTypeOut,
    EventTypeUpdateIn,
    ImportResultOut,
    RuleCreateIn,
    RuleOut,
    RuleUpdateIn,
    SiteCreateIn,
    SiteOut,
    SiteUpdateIn,
)
from app.schemas.common import Page
from app.schemas.operations import RuleTestIn, RuleTestOut
from app.services import catalog, events, imports
from app.services.context import Ctx
from app.services.permissions import Permission
from app.services.scoping import get_or_404, paginate, scoped

router = APIRouter(tags=["configuration"])

Reader = Annotated[Ctx, Depends(require(Permission.READ))]
Configurer = Annotated[Ctx, Depends(require(Permission.CONFIGURE))]
ActiveFilter = Annotated[bool | None, Query(description="Filter by active flag; omit for all")]
Search = Annotated[str | None, Query(max_length=100, description="Match code or name")]


def _page(session, stmt, page) -> Page:
    items, total = paginate(session, stmt, limit=page.limit, offset=page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _read_upload(file: UploadFile) -> bytes:
    limit = get_settings().import_max_bytes
    raw = file.file.read(limit + 1)  # sync read: these routes run in the threadpool
    if len(raw) > limit:
        raise PayloadTooLarge(f"The file is larger than {limit} bytes.")
    if not raw:
        raise ValidationFailed("The file is empty.", code="EMPTY_FILE")
    return raw


# ------------------------------------------------------------------- sites


@router.get("/sites", response_model=Page[SiteOut])
def list_sites(ctx: Reader, session: DB, page: PageParams, active: ActiveFilter = None, q: Search = None):
    stmt = scoped(Site, ctx.org_id).order_by(Site.code)
    if active is not None:
        stmt = stmt.where(Site.is_active.is_(active))
    if q:
        stmt = stmt.where(or_(Site.code.ilike(_like(q), escape="\\"), Site.name.ilike(_like(q), escape="\\")))
    return _page(session, stmt, page)


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
def create_site(body: SiteCreateIn, ctx: Configurer, session: DB):
    site = catalog.create_site(session, ctx, body)
    session.commit()
    return site


@router.post("/sites/import", response_model=ImportResultOut)
def import_sites(
    ctx: Configurer,
    session: DB,
    file: Annotated[UploadFile, File(description="CSV with code, name, kind, latitude, longitude, timezone")],
    upsert: bool = False,
    dry_run: bool = False,
):
    raw = _read_upload(file)
    result = imports.import_sites(session, ctx, raw, upsert=upsert, dry_run=dry_run)
    if result.errors:
        session.rollback()
        raise ValidationFailed(
            "The file has errors; nothing was imported.",
            code="IMPORT_FAILED",
            details=[e.__dict__ for e in result.errors[:500]],
        )
    session.commit()
    return result


@router.get("/sites/{site_id}", response_model=SiteOut)
def get_site(site_id: uuid.UUID, ctx: Reader, session: DB):
    return get_or_404(session, Site, ctx.org_id, site_id, label="Site")


@router.patch("/sites/{site_id}", response_model=SiteOut)
def update_site(site_id: uuid.UUID, body: SiteUpdateIn, ctx: Configurer, session: DB):
    site = catalog.update_site(session, ctx, site_id, body)
    session.commit()
    return site


# ------------------------------------------------------------------ assets


@router.get("/assets", response_model=Page[AssetOut])
def list_assets(
    ctx: Reader,
    session: DB,
    page: PageParams,
    site_id: uuid.UUID | None = None,
    active: ActiveFilter = None,
    q: Search = None,
):
    stmt = scoped(Asset, ctx.org_id).order_by(Asset.code)
    if site_id is not None:
        stmt = stmt.where(Asset.site_id == site_id)
    if active is not None:
        stmt = stmt.where(Asset.is_active.is_(active))
    if q:
        stmt = stmt.where(or_(Asset.code.ilike(_like(q), escape="\\"), Asset.name.ilike(_like(q), escape="\\")))
    return _page(session, stmt, page)


@router.post("/assets", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(body: AssetCreateIn, ctx: Configurer, session: DB):
    asset = catalog.create_asset(session, ctx, body)
    session.commit()
    return asset


@router.post("/assets/import", response_model=ImportResultOut)
def import_assets(
    ctx: Configurer,
    session: DB,
    file: Annotated[UploadFile, File(description="CSV with code, name, site_code, asset_type, criticality")],
    upsert: bool = False,
    dry_run: bool = False,
):
    raw = _read_upload(file)
    result = imports.import_assets(session, ctx, raw, upsert=upsert, dry_run=dry_run)
    if result.errors:
        session.rollback()
        raise ValidationFailed(
            "The file has errors; nothing was imported.",
            code="IMPORT_FAILED",
            details=[e.__dict__ for e in result.errors[:500]],
        )
    session.commit()
    return result


@router.get("/assets/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: uuid.UUID, ctx: Reader, session: DB):
    return get_or_404(session, Asset, ctx.org_id, asset_id, label="Asset")


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: uuid.UUID, body: AssetUpdateIn, ctx: Configurer, session: DB):
    asset = catalog.update_asset(session, ctx, asset_id, body)
    session.commit()
    return asset


# ---------------------------------------------------------------- contacts


@router.get("/contacts", response_model=Page[ContactOut])
def list_contacts(ctx: Reader, session: DB, page: PageParams, active: ActiveFilter = None, role: str | None = None):
    stmt = scoped(Contact, ctx.org_id).order_by(Contact.name)
    if active is not None:
        stmt = stmt.where(Contact.is_active.is_(active))
    if role:
        stmt = stmt.where(Contact.role_label == role.strip().casefold())
    return _page(session, stmt, page)


@router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(body: ContactCreateIn, ctx: Configurer, session: DB):
    contact = catalog.create_contact(session, ctx, body)
    session.commit()
    return contact


@router.get("/contacts/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: uuid.UUID, ctx: Reader, session: DB):
    return get_or_404(session, Contact, ctx.org_id, contact_id, label="Contact")


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: uuid.UUID, body: ContactUpdateIn, ctx: Configurer, session: DB):
    contact = catalog.update_contact(session, ctx, contact_id, body)
    session.commit()
    return contact


# ------------------------------------------------------------- event types


@router.get("/event-types", response_model=Page[EventTypeOut])
def list_event_types(ctx: Reader, session: DB, page: PageParams, active: ActiveFilter = None):
    stmt = scoped(EventType, ctx.org_id).order_by(EventType.key)
    if active is not None:
        stmt = stmt.where(EventType.is_active.is_(active))
    return _page(session, stmt, page)


@router.post("/event-types", response_model=EventTypeOut, status_code=status.HTTP_201_CREATED)
def create_event_type(body: EventTypeCreateIn, ctx: Configurer, session: DB):
    event_type = catalog.create_event_type(session, ctx, body)
    session.commit()
    return event_type


@router.get("/event-types/{type_id}", response_model=EventTypeOut)
def get_event_type(type_id: uuid.UUID, ctx: Reader, session: DB):
    return get_or_404(session, EventType, ctx.org_id, type_id, label="Event type")


@router.patch("/event-types/{type_id}", response_model=EventTypeOut)
def update_event_type(type_id: uuid.UUID, body: EventTypeUpdateIn, ctx: Configurer, session: DB):
    event_type = catalog.update_event_type(session, ctx, type_id, body)
    session.commit()
    return event_type


# ------------------------------------------------------------------- rules


@router.get("/rules", response_model=Page[RuleOut])
def list_rules(ctx: Reader, session: DB, page: PageParams, active: ActiveFilter = None):
    stmt = scoped(Rule, ctx.org_id).order_by(Rule.priority, Rule.name)
    if active is not None:
        stmt = stmt.where(Rule.is_active.is_(active))
    return _page(session, stmt, page)


@router.post("/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleCreateIn, ctx: Configurer, session: DB):
    rule = catalog.create_rule(session, ctx, body)
    session.commit()
    return rule


@router.get("/rules/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: uuid.UUID, ctx: Reader, session: DB):
    return get_or_404(session, Rule, ctx.org_id, rule_id, label="Rule")


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, body: RuleUpdateIn, ctx: Configurer, session: DB):
    rule = catalog.update_rule(session, ctx, rule_id, body)
    session.commit()
    return rule


@router.post("/rules/{rule_id}/test", response_model=RuleTestOut)
def test_rule(rule_id: uuid.UUID, body: RuleTestIn, ctx: Configurer, session: DB):
    """Try a rule against a sample event. Nothing is stored or sent."""
    result = events.dry_run_rule(session, ctx, rule_id, body.event)
    session.rollback()
    return RuleTestOut(**result.__dict__)
