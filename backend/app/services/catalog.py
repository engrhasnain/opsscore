"""Client configuration: sites, assets, contacts, event types and rules.

Records referenced by history (events, alerts) are deactivated, never deleted,
so evidence keeps pointing at real rows.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, ValidationFailed
from app.models import Asset, Contact, EventType, Rule, Site
from app.schemas.catalog import (
    AssetCreateIn,
    AssetUpdateIn,
    ContactCreateIn,
    ContactUpdateIn,
    EventTypeCreateIn,
    EventTypeUpdateIn,
    RuleCreateIn,
    RuleUpdateIn,
    SiteCreateIn,
    SiteUpdateIn,
)
from app.services import attributes as attr
from app.services import audit
from app.services import rules as rules_engine
from app.services import validation as v
from app.services.context import Ctx
from app.services.scoping import get_or_404, scoped


def _snapshot(obj, fields: list[str]) -> dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


def _check_attribute_map(values: dict[str, Any] | None) -> dict[str, Any]:
    values = values or {}
    for key_name, value in values.items():
        if not attr.ATTR_NAME.match(key_name):
            raise ValidationFailed(f"attribute name {key_name!r} must use lowercase letters, digits and _.")
        if isinstance(value, str) and len(value) > attr.MAX_STRING:
            raise ValidationFailed(f"attribute {key_name!r} is too long.")
    return dict(values)


# ------------------------------------------------------------------- sites

_SITE_FIELDS = ["code", "name", "kind", "latitude", "longitude", "timezone", "attributes", "is_active"]


def site_by_code(session: Session, org_id: uuid.UUID, site_code: str) -> Site | None:
    return session.scalar(scoped(Site, org_id).where(Site.code == v.code(site_code, field="site_code")))


def _ensure_site_code_free(session: Session, ctx: Ctx, site_code: str, exclude: uuid.UUID | None = None):
    stmt = scoped(Site, ctx.org_id).where(Site.code == site_code)
    if exclude:
        stmt = stmt.where(Site.id != exclude)
    if session.scalar(stmt) is not None:
        raise Conflict(f"A site with code {site_code} already exists.", code="DUPLICATE_CODE")


def create_site(session: Session, ctx: Ctx, data: SiteCreateIn) -> Site:
    site_code = v.code(data.code)
    _ensure_site_code_free(session, ctx, site_code)
    site = Site(
        org_id=ctx.org_id,
        code=site_code,
        name=v.text(data.name, field="name", max_length=200),
        kind=v.kind(data.kind),
        latitude=v.coordinate(data.latitude, field="latitude", low=-90, high=90),
        longitude=v.coordinate(data.longitude, field="longitude", low=-180, high=180),
        timezone=v.timezone(data.timezone),
        attributes=_check_attribute_map(data.attributes),
    )
    if (site.latitude is None) != (site.longitude is None):
        raise ValidationFailed("Give both latitude and longitude, or neither.")
    session.add(site)
    session.flush()
    audit.record(session, ctx, "site.created", "site", site.id, _snapshot(site, _SITE_FIELDS))
    return site


def update_site(session: Session, ctx: Ctx, site_id: uuid.UUID, data: SiteUpdateIn) -> Site:
    site = get_or_404(session, Site, ctx.org_id, site_id, label="Site", for_update=True)
    before = _snapshot(site, _SITE_FIELDS)
    changes = data.provided()
    if "code" in changes and changes["code"] is not None:
        new_code = v.code(changes["code"])
        _ensure_site_code_free(session, ctx, new_code, exclude=site.id)
        site.code = new_code
    if changes.get("name") is not None:
        site.name = v.text(changes["name"], field="name", max_length=200)
    if "kind" in changes:
        site.kind = v.kind(changes["kind"])
    if "latitude" in changes:
        site.latitude = v.coordinate(changes["latitude"], field="latitude", low=-90, high=90)
    if "longitude" in changes:
        site.longitude = v.coordinate(changes["longitude"], field="longitude", low=-180, high=180)
    if (site.latitude is None) != (site.longitude is None):
        raise ValidationFailed("Give both latitude and longitude, or neither.")
    if "timezone" in changes:
        site.timezone = v.timezone(changes["timezone"])
    if changes.get("attributes") is not None:
        site.attributes = _check_attribute_map(changes["attributes"])
    if changes.get("is_active") is not None:
        site.is_active = changes["is_active"]
    session.flush()
    audit.record(session, ctx, "site.updated", "site", site.id, audit.diff(before, _snapshot(site, _SITE_FIELDS)))
    return site


# ------------------------------------------------------------------ assets

_ASSET_FIELDS = ["site_id", "code", "name", "asset_type", "criticality", "attributes", "is_active"]


def _resolve_site(session: Session, ctx: Ctx, site_id: uuid.UUID | None, site_code: str | None) -> Site:
    if site_id is None and not site_code:
        raise ValidationFailed("Give site_id or site_code.")
    site = None
    if site_id is not None:
        site = get_or_404(session, Site, ctx.org_id, site_id, label="Site")
    if site_code:
        by_code = site_by_code(session, ctx.org_id, site_code)
        if by_code is None:
            raise ValidationFailed(f"No site with code {site_code}.", code="UNKNOWN_SITE")
        if site is not None and site.id != by_code.id:
            raise ValidationFailed("site_id and site_code point at different sites.")
        site = by_code
    return site


def _ensure_asset_code_free(session: Session, ctx: Ctx, asset_code: str, exclude: uuid.UUID | None = None):
    stmt = scoped(Asset, ctx.org_id).where(Asset.code == asset_code)
    if exclude:
        stmt = stmt.where(Asset.id != exclude)
    if session.scalar(stmt) is not None:
        raise Conflict(f"An asset with code {asset_code} already exists.", code="DUPLICATE_CODE")


def create_asset(session: Session, ctx: Ctx, data: AssetCreateIn) -> Asset:
    site = _resolve_site(session, ctx, data.site_id, data.site_code)
    asset_code = v.code(data.code)
    _ensure_asset_code_free(session, ctx, asset_code)
    asset = Asset(
        org_id=ctx.org_id,
        site_id=site.id,
        code=asset_code,
        name=v.text(data.name, field="name", max_length=200),
        asset_type=v.kind(data.asset_type, default="equipment"),
        criticality=data.criticality,
        attributes=_check_attribute_map(data.attributes),
    )
    session.add(asset)
    session.flush()
    audit.record(session, ctx, "asset.created", "asset", asset.id, _snapshot(asset, _ASSET_FIELDS))
    return asset


def update_asset(session: Session, ctx: Ctx, asset_id: uuid.UUID, data: AssetUpdateIn) -> Asset:
    asset = get_or_404(session, Asset, ctx.org_id, asset_id, label="Asset", for_update=True)
    before = _snapshot(asset, _ASSET_FIELDS)
    changes = data.provided()
    if changes.get("site_id") is not None:
        asset.site_id = get_or_404(session, Site, ctx.org_id, changes["site_id"], label="Site").id
    if changes.get("code") is not None:
        new_code = v.code(changes["code"])
        _ensure_asset_code_free(session, ctx, new_code, exclude=asset.id)
        asset.code = new_code
    if changes.get("name") is not None:
        asset.name = v.text(changes["name"], field="name", max_length=200)
    if changes.get("asset_type") is not None:
        asset.asset_type = v.kind(changes["asset_type"], default="equipment")
    if changes.get("criticality") is not None:
        asset.criticality = changes["criticality"]
    if changes.get("attributes") is not None:
        asset.attributes = _check_attribute_map(changes["attributes"])
    if changes.get("is_active") is not None:
        asset.is_active = changes["is_active"]
    session.flush()
    audit.record(session, ctx, "asset.updated", "asset", asset.id, audit.diff(before, _snapshot(asset, _ASSET_FIELDS)))
    return asset


# ---------------------------------------------------------------- contacts

_CONTACT_FIELDS = ["name", "role_label", "email", "phone", "whatsapp", "locale", "is_active"]


def _role_label(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip().casefold()


def create_contact(session: Session, ctx: Ctx, data: ContactCreateIn) -> Contact:
    contact = Contact(
        org_id=ctx.org_id,
        name=v.text(data.name, field="name", max_length=200),
        role_label=_role_label(data.role_label),
        email=str(data.email).lower() if data.email else None,
        phone=v.phone(data.phone),
        whatsapp=v.phone(data.whatsapp, field="whatsapp"),
        locale=data.locale,
    )
    if not (contact.email or contact.phone or contact.whatsapp):
        raise ValidationFailed("A contact needs at least an email, phone or WhatsApp number.")
    session.add(contact)
    session.flush()
    audit.record(session, ctx, "contact.created", "contact", contact.id, _snapshot(contact, _CONTACT_FIELDS))
    return contact


def update_contact(session: Session, ctx: Ctx, contact_id: uuid.UUID, data: ContactUpdateIn) -> Contact:
    contact = get_or_404(session, Contact, ctx.org_id, contact_id, label="Contact", for_update=True)
    before = _snapshot(contact, _CONTACT_FIELDS)
    changes = data.provided()
    if changes.get("name") is not None:
        contact.name = v.text(changes["name"], field="name", max_length=200)
    if "role_label" in changes:
        contact.role_label = _role_label(changes["role_label"])
    if "email" in changes:
        contact.email = str(changes["email"]).lower() if changes["email"] else None
    if "phone" in changes:
        contact.phone = v.phone(changes["phone"])
    if "whatsapp" in changes:
        contact.whatsapp = v.phone(changes["whatsapp"], field="whatsapp")
    if "locale" in changes:
        contact.locale = changes["locale"]
    if changes.get("is_active") is not None:
        contact.is_active = changes["is_active"]
    if not (contact.email or contact.phone or contact.whatsapp):
        raise ValidationFailed("A contact needs at least an email, phone or WhatsApp number.")
    session.flush()
    audit.record(
        session, ctx, "contact.updated", "contact", contact.id, audit.diff(before, _snapshot(contact, _CONTACT_FIELDS))
    )
    return contact


# ------------------------------------------------------------- event types

_EVENT_TYPE_FIELDS = ["name", "description", "category", "default_severity", "attributes_schema", "is_active"]


def event_type_by_key(session: Session, org_id: uuid.UUID, type_key: str) -> EventType | None:
    return session.scalar(scoped(EventType, org_id).where(EventType.key == type_key.strip().lower()))


def create_event_type(session: Session, ctx: Ctx, data: EventTypeCreateIn, *, is_system: bool = False) -> EventType:
    type_key = v.key(data.key)
    if event_type_by_key(session, ctx.org_id, type_key) is not None:
        raise Conflict(f"Event type {type_key} already exists.", code="DUPLICATE_KEY")
    event_type = EventType(
        org_id=ctx.org_id,
        key=type_key,
        name=v.text(data.name, field="name", max_length=200),
        description=v.text(data.description, field="description", max_length=1000, required=False),
        category=data.category,
        default_severity=data.default_severity,
        attributes_schema=attr.validate_schema(data.attributes_schema),
        is_system=is_system,
    )
    session.add(event_type)
    session.flush()
    audit.record(
        session,
        ctx,
        "event_type.created",
        "event_type",
        event_type.id,
        {"key": type_key, **_snapshot(event_type, _EVENT_TYPE_FIELDS)},
    )
    return event_type


def update_event_type(session: Session, ctx: Ctx, type_id: uuid.UUID, data: EventTypeUpdateIn) -> EventType:
    event_type = get_or_404(session, EventType, ctx.org_id, type_id, label="Event type", for_update=True)
    before = _snapshot(event_type, _EVENT_TYPE_FIELDS)
    changes = data.provided()
    if changes.get("name") is not None:
        event_type.name = v.text(changes["name"], field="name", max_length=200)
    if "description" in changes:
        event_type.description = v.text(changes["description"], field="description", max_length=1000, required=False)
    if changes.get("category") is not None:
        event_type.category = changes["category"]
    if changes.get("default_severity") is not None:
        event_type.default_severity = changes["default_severity"]
    if changes.get("attributes_schema") is not None:
        new_schema = attr.validate_schema(changes["attributes_schema"])
        _ensure_rules_still_valid(session, ctx, event_type, new_schema)
        event_type.attributes_schema = new_schema
    if changes.get("is_active") is not None:
        if event_type.is_system and not changes["is_active"]:
            raise Conflict("Built-in event types cannot be deactivated.", code="SYSTEM_EVENT_TYPE")
        event_type.is_active = changes["is_active"]
    session.flush()
    audit.record(
        session,
        ctx,
        "event_type.updated",
        "event_type",
        event_type.id,
        audit.diff(before, _snapshot(event_type, _EVENT_TYPE_FIELDS)),
    )
    return event_type


def _ensure_rules_still_valid(session: Session, ctx: Ctx, event_type: EventType, new_schema: list[dict]) -> None:
    """Refuse a schema change that would silently break existing rules."""
    rules = session.scalars(
        scoped(Rule, ctx.org_id).where(Rule.event_type_id == event_type.id, Rule.is_active.is_(True))
    )
    broken = []
    for rule in rules:
        try:
            rules_engine.validate_conditions(rule.conditions, attribute_schema=new_schema)
        except ValidationFailed as exc:
            broken.append({"rule_id": str(rule.id), "rule": rule.name, "problems": exc.details})
    if broken:
        raise Conflict(
            "This change would break active rules. Update or deactivate them first.",
            code="RULES_DEPEND_ON_SCHEMA",
            details=broken,
        )


# ------------------------------------------------------------------- rules

_RULE_FIELDS = [
    "name",
    "description",
    "event_type_id",
    "match",
    "conditions",
    "actions",
    "severity_override",
    "renotify_after_seconds",
    "priority",
    "is_active",
]


def _resolve_rule_event_type(session: Session, ctx: Ctx, type_key: str | None) -> EventType | None:
    if not type_key:
        return None
    event_type = event_type_by_key(session, ctx.org_id, type_key)
    if event_type is None:
        raise ValidationFailed(f"No event type with key {type_key}.", code="UNKNOWN_EVENT_TYPE")
    return event_type


def _check_contacts_exist(session: Session, ctx: Ctx, actions: list[dict]) -> None:
    wanted = rules_engine.referenced_contact_ids(actions)
    if not wanted:
        return
    found = set(session.scalars(select(Contact.id).where(Contact.org_id == ctx.org_id, Contact.id.in_(wanted))))
    missing = wanted - found
    if missing:
        raise ValidationFailed(
            "Some contacts in the actions do not exist.",
            code="UNKNOWN_CONTACT",
            details=sorted(str(m) for m in missing),
        )


def create_rule(session: Session, ctx: Ctx, data: RuleCreateIn) -> Rule:
    event_type = _resolve_rule_event_type(session, ctx, data.event_type)
    schema = event_type.attributes_schema if event_type else None
    actions = rules_engine.validate_actions(data.actions)
    _check_contacts_exist(session, ctx, actions)
    rule = Rule(
        org_id=ctx.org_id,
        name=v.text(data.name, field="name", max_length=200),
        description=v.text(data.description, field="description", max_length=1000, required=False),
        event_type_id=event_type.id if event_type else None,
        match=rules_engine.validate_match(data.match),
        conditions=rules_engine.validate_conditions(data.conditions, attribute_schema=schema),
        actions=actions,
        severity_override=data.severity_override,
        renotify_after_seconds=data.renotify_after_seconds,
        priority=data.priority,
    )
    session.add(rule)
    session.flush()
    audit.record(session, ctx, "rule.created", "rule", rule.id, _snapshot(rule, _RULE_FIELDS))
    return rule


def update_rule(session: Session, ctx: Ctx, rule_id: uuid.UUID, data: RuleUpdateIn) -> Rule:
    rule = get_or_404(session, Rule, ctx.org_id, rule_id, label="Rule", for_update=True)
    before = _snapshot(rule, _RULE_FIELDS)
    changes = data.provided()

    event_type = None
    if "event_type" in changes:
        event_type = _resolve_rule_event_type(session, ctx, changes["event_type"])
        rule.event_type_id = event_type.id if event_type else None
    elif rule.event_type_id:
        event_type = session.get(EventType, rule.event_type_id)
    schema = event_type.attributes_schema if event_type else None

    if changes.get("name") is not None:
        rule.name = v.text(changes["name"], field="name", max_length=200)
    if "description" in changes:
        rule.description = v.text(changes["description"], field="description", max_length=1000, required=False)
    if changes.get("match") is not None:
        rule.match = rules_engine.validate_match(changes["match"])
    # Conditions are re-checked even when unchanged: the event type may have changed.
    rule.conditions = rules_engine.validate_conditions(
        changes["conditions"] if changes.get("conditions") is not None else rule.conditions,
        attribute_schema=schema,
    )
    if changes.get("actions") is not None:
        actions = rules_engine.validate_actions(changes["actions"])
        _check_contacts_exist(session, ctx, actions)
        rule.actions = actions
    if "severity_override" in changes:
        rule.severity_override = changes["severity_override"]
    if changes.get("renotify_after_seconds") is not None:
        rule.renotify_after_seconds = changes["renotify_after_seconds"]
    if changes.get("priority") is not None:
        rule.priority = changes["priority"]
    if changes.get("is_active") is not None:
        rule.is_active = changes["is_active"]
    session.flush()
    audit.record(session, ctx, "rule.updated", "rule", rule.id, audit.diff(before, _snapshot(rule, _RULE_FIELDS)))
    return rule


def count_active(session: Session, model, org_id: uuid.UUID) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(model.org_id == org_id, model.is_active.is_(True)))
        or 0
    )
