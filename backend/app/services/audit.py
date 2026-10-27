"""Tamper-evident audit trail.

Entries form a hash chain per organization:

    hash_n = sha256(canonical(entry_n fields) + hash_{n-1})

The organization row holds the chain head and is locked while appending, so
concurrent writers cannot fork the chain.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import AuditEntry, Organization
from app.request_context import current_request_id
from app.services.context import Ctx

GENESIS_HASH = "0" * 64


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def to_jsonable(value: Any) -> Any:
    """UUIDs, datetimes and enums become strings, so JSON columns accept them."""
    return json.loads(canonical(value))


def _entry_hash(entry: AuditEntry) -> str:
    material = canonical(
        {
            "org_id": str(entry.org_id),
            "seq": entry.seq,
            "created_at": entry.created_at.isoformat(),
            "actor_type": str(entry.actor_type),
            "actor_id": entry.actor_id,
            "action": entry.action,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "changes": entry.changes,
            "request_id": entry.request_id,
            "prev_hash": entry.prev_hash,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record(
    session: Session,
    ctx: Ctx,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None = None,
    changes: dict | None = None,
) -> AuditEntry:
    org = session.execute(
        select(Organization)
        .where(Organization.id == ctx.org_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()

    entry = AuditEntry(
        id=uuid.uuid4(),
        org_id=org.id,
        seq=org.audit_seq + 1,
        created_at=utcnow(),
        actor_type=ctx.actor.type,
        actor_id=ctx.actor.id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        changes=to_jsonable(changes or {}),
        request_id=current_request_id(),
        prev_hash=org.audit_head_hash or GENESIS_HASH,
    )
    entry.hash = _entry_hash(entry)
    org.audit_seq = entry.seq
    org.audit_head_hash = entry.hash
    session.add(entry)
    session.flush()
    return entry


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Field-level changes, for audit entries on updates."""
    changed = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed[key] = {"from": before.get(key), "to": after.get(key)}
    return to_jsonable(changed)


@dataclass
class ChainReport:
    valid: bool
    entries_checked: int
    first_invalid_seq: int | None = None
    reason: str | None = None


def verify_chain(session: Session, org_id: uuid.UUID) -> ChainReport:
    org = session.get(Organization, org_id)
    if org is None:
        return ChainReport(valid=False, entries_checked=0, reason="organization not found")

    stmt = (
        select(AuditEntry).where(AuditEntry.org_id == org_id).order_by(AuditEntry.seq).execution_options(yield_per=500)
    )
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    for entry in session.scalars(stmt):
        if entry.seq != expected_seq:
            return ChainReport(False, checked, expected_seq, "entry missing from sequence")
        if entry.prev_hash != expected_prev:
            return ChainReport(False, checked, entry.seq, "link to previous entry is broken")
        if _entry_hash(entry) != entry.hash:
            return ChainReport(False, checked, entry.seq, "entry content was modified")
        expected_prev = entry.hash
        expected_seq += 1
        checked += 1

    if checked != org.audit_seq:
        return ChainReport(False, checked, checked + 1, "entries removed from the end")
    if checked and expected_prev != org.audit_head_hash:
        return ChainReport(False, checked, checked, "chain head does not match")
    return ChainReport(valid=True, entries_checked=checked)
