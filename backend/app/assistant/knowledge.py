"""The client's approved answers. Only these may be sent by the assistant."""

import uuid

from sqlalchemy.orm import Session

from app.models import KnowledgeEntry, Site
from app.schemas.assistant import KnowledgeCreateIn, KnowledgeUpdateIn
from app.services import audit
from app.services.context import Ctx
from app.services.scoping import get_or_404

_FIELDS = ["title", "content", "keywords", "locale", "site_id", "is_active"]


def _keywords(values: list[str]) -> list[str]:
    return list(dict.fromkeys(k.strip().casefold() for k in values if k.strip()))


def create(session: Session, ctx: Ctx, data: KnowledgeCreateIn) -> KnowledgeEntry:
    if data.site_id is not None:
        get_or_404(session, Site, ctx.org_id, data.site_id, label="Site")
    entry = KnowledgeEntry(
        org_id=ctx.org_id,
        title=data.title,
        content=data.content,
        keywords=_keywords(data.keywords),
        locale=data.locale,
        site_id=data.site_id,
    )
    session.add(entry)
    session.flush()
    audit.record(
        session, ctx, "knowledge.created", "knowledge_entry", entry.id, {f: getattr(entry, f) for f in _FIELDS}
    )
    return entry


def update(session: Session, ctx: Ctx, entry_id: uuid.UUID, data: KnowledgeUpdateIn) -> KnowledgeEntry:
    entry = get_or_404(session, KnowledgeEntry, ctx.org_id, entry_id, label="Knowledge entry", for_update=True)
    before = {f: getattr(entry, f) for f in _FIELDS}
    changes = data.provided()
    for name in ("title", "content", "locale", "is_active"):
        if changes.get(name) is not None:
            setattr(entry, name, changes[name])
    if changes.get("keywords") is not None:
        entry.keywords = _keywords(changes["keywords"])
    if "site_id" in changes:
        if changes["site_id"] is not None:
            get_or_404(session, Site, ctx.org_id, changes["site_id"], label="Site")
        entry.site_id = changes["site_id"]
    session.flush()
    audit.record(
        session,
        ctx,
        "knowledge.updated",
        "knowledge_entry",
        entry.id,
        audit.diff(before, {f: getattr(entry, f) for f in _FIELDS}),
    )
    return entry


def delete(session: Session, ctx: Ctx, entry_id: uuid.UUID) -> None:
    entry = get_or_404(session, KnowledgeEntry, ctx.org_id, entry_id, label="Knowledge entry", for_update=True)
    audit.record(
        session, ctx, "knowledge.deleted", "knowledge_entry", entry.id, {f: getattr(entry, f) for f in _FIELDS}
    )
    session.delete(entry)
    session.flush()
