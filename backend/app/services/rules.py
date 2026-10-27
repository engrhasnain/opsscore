"""The rules engine: what clients configure instead of asking for code changes.

A rule has conditions (when) and actions (what to do):

    {
      "match": "all",
      "conditions": [
        {"field": "attributes.ppm", "op": "gte", "value": 10},
        {"field": "asset.criticality", "op": "gte", "value": 4}
      ],
      "actions": [
        {"type": "notify", "channels": ["sms", "email"], "contact_roles": ["safety_lead"]},
        {"type": "create_work_order", "title": "Inspect {asset.name}", "priority": "urgent",
         "due_in_hours": 4}
      ]
    }

Evaluation is pure and total: a malformed value or a missing attribute makes a
condition false. It never raises, because one bad event must not stop the
other rules from running.
"""

import math
import re
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.enums import SEVERITY_RANK, Channel, Severity, WorkOrderPriority
from app.errors import ValidationFailed
from app.services.templating import validate_template

MAX_CONDITIONS = 20
MAX_ACTIONS = 10
MAX_LIST_VALUES = 100

_FIELD = re.compile(
    r"^(severity|event_type|source\.type|local_hour|local_weekday"
    r"|site\.(code|kind|name)|asset\.(code|type|name|criticality)"
    r"|attributes\.[a-z][a-z0-9_]{0,63})$"
)
_NUMERIC_FIELDS = {"asset.criticality", "local_hour", "local_weekday"}
_FIELD_RANGES = {"local_hour": (0, 23), "local_weekday": (0, 6), "asset.criticality": (1, 5)}
_ORDER_OPS = {"gt", "gte", "lt", "lte"}
_LIST_OPS = {"in", "not_in"}
_PRESENCE_OPS = {"exists", "not_exists"}
OPS = _ORDER_OPS | _LIST_OPS | _PRESENCE_OPS | {"eq", "ne", "contains"}


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_scalar(value: Any) -> bool:
    return isinstance(value, str | bool) or _is_number(value)


def _value_mismatch(name: str, definition: dict, op: str, value: Any) -> str | None:
    """A value that can never equal the attribute (wrong type, or not an allowed choice)
    makes a rule that silently never fires, so refuse it when the rule is saved."""
    kind = definition["type"]
    if op == "contains":
        return None if kind == "string" and isinstance(value, str) else "'contains' needs text on a text attribute"
    values = value if isinstance(value, list) else [value]
    if kind in ("number", "integer") and not all(_is_number(v) for v in values):
        return f"attribute {name!r} is a number; compare it with a number, not text"
    if kind == "boolean" and not all(isinstance(v, bool) for v in values):
        return f"attribute {name!r} is true/false; use true or false"
    if kind == "string":
        if not all(isinstance(v, str) for v in values):
            return f"attribute {name!r} is text; compare it with text"
        allowed = definition.get("enum")
        if allowed:
            known = {str(a).casefold() for a in allowed}
            unknown = [v for v in values if v.casefold() not in known]
            if unknown:
                return f"{unknown} not among the allowed values for {name!r}: {allowed}"
    return None


# ---------------------------------------------------------------- validation


def validate_conditions(conditions: Any, *, attribute_schema: list[dict] | None) -> list[dict]:
    """Return normalized conditions or raise ValidationFailed listing every problem.

    ``attribute_schema`` is the event type's schema when the rule targets one
    type; then attribute names and types are checked too.
    """
    if conditions is None:
        return []
    if not isinstance(conditions, list):
        raise ValidationFailed("conditions must be a list.")
    if len(conditions) > MAX_CONDITIONS:
        raise ValidationFailed(f"A rule can have at most {MAX_CONDITIONS} conditions.")

    declared = {item["name"]: item for item in attribute_schema} if attribute_schema else None
    problems: list[dict] = []
    normalized: list[dict] = []

    for index, raw in enumerate(conditions):
        where = f"conditions[{index}]"
        if not isinstance(raw, dict):
            problems.append({"field": where, "message": "must be an object"})
            continue
        extra = set(raw) - {"field", "op", "value"}
        if extra:
            problems.append({"field": where, "message": f"unknown keys: {sorted(extra)}"})
        field, op = raw.get("field"), raw.get("op")
        if not isinstance(field, str) or not _FIELD.match(field):
            problems.append({"field": f"{where}.field", "message": f"unknown field {field!r}"})
            continue
        if op not in OPS:
            problems.append({"field": f"{where}.op", "message": f"must be one of {sorted(OPS)}"})
            continue

        has_value = "value" in raw
        value = raw.get("value")
        problem = None
        if op in _PRESENCE_OPS:
            if has_value:
                problem = f"'{op}' takes no value"
        elif not has_value:
            problem = "value is required"
        elif op in _LIST_OPS:
            if (
                not isinstance(value, list)
                or not 1 <= len(value) <= MAX_LIST_VALUES
                or not all(_is_scalar(v) for v in value)
            ):
                problem = f"value must be a list of 1-{MAX_LIST_VALUES} plain values"
        elif not _is_scalar(value):
            problem = "value must be text, a number or true/false"
        elif op in _ORDER_OPS:
            if field == "severity":
                if value not in SEVERITY_RANK:
                    problem = f"value must be a severity: {[s.value for s in Severity]}"
            elif field not in _NUMERIC_FIELDS and not field.startswith("attributes."):
                problem = f"{field} is text; use eq, ne, in, not_in or contains"
            elif not _is_number(value):
                problem = "value must be a number for this comparison"

        if problem is None and field == "severity" and op not in _PRESENCE_OPS:
            values = value if isinstance(value, list) else [value]
            if any(v not in SEVERITY_RANK for v in values):
                problem = f"severity must be one of {[s.value for s in Severity]}"

        if problem is None and field in _FIELD_RANGES and op not in _PRESENCE_OPS:
            low, high = _FIELD_RANGES[field]
            values = value if isinstance(value, list) else [value]
            if not all(_is_number(v) and low <= v <= high for v in values):
                problem = f"value must be a number from {low} to {high}"

        if problem is None and declared is not None and field.startswith("attributes."):
            name = field.split(".", 1)[1]
            definition = declared.get(name)
            if definition is None:
                problem = f"attribute {name!r} is not declared for this event type"
            elif op in _ORDER_OPS and definition["type"] not in ("number", "integer"):
                problem = f"attribute {name!r} is {definition['type']}, it cannot be compared"
            elif op not in _PRESENCE_OPS:
                problem = _value_mismatch(name, definition, op, value)

        if problem:
            problems.append({"field": where, "message": problem})
            continue
        item = {"field": field, "op": op}
        if has_value:
            item["value"] = value
        normalized.append(item)

    if problems:
        raise ValidationFailed("Rule conditions are not valid.", details=problems)
    return normalized


def validate_actions(actions: Any) -> list[dict]:
    """Structural validation. Contact ids are checked against the database by the caller."""
    if actions is None:
        return []
    if not isinstance(actions, list):
        raise ValidationFailed("actions must be a list.")
    if len(actions) > MAX_ACTIONS:
        raise ValidationFailed(f"A rule can have at most {MAX_ACTIONS} actions.")

    problems: list[dict] = []
    normalized: list[dict] = []
    work_orders = 0
    for index, raw in enumerate(actions):
        where = f"actions[{index}]"
        if not isinstance(raw, dict):
            problems.append({"field": where, "message": "must be an object"})
            continue
        kind = raw.get("type")
        try:
            if kind == "notify":
                normalized.append(_validate_notify(raw))
            elif kind == "create_work_order":
                work_orders += 1
                if work_orders > 1:
                    raise ValidationFailed("only one create_work_order action is allowed")
                normalized.append(_validate_work_order(raw))
            else:
                raise ValidationFailed("type must be 'notify' or 'create_work_order'")
        except ValidationFailed as exc:
            problems.append({"field": where, "message": exc.message, "details": exc.details})

    if problems:
        raise ValidationFailed("Rule actions are not valid.", details=problems)
    return normalized


def _validate_notify(raw: dict) -> dict:
    extra = set(raw) - {"type", "channels", "contact_ids", "contact_roles"}
    if extra:
        raise ValidationFailed(f"unknown keys: {sorted(extra)}")
    channels = raw.get("channels")
    if not isinstance(channels, list) or not channels:
        raise ValidationFailed("channels must list at least one channel")
    try:
        channels = list(dict.fromkeys(Channel(c).value for c in channels))
    except (ValueError, TypeError):
        raise ValidationFailed(f"channels must be from {[c.value for c in Channel]}") from None

    contact_ids = raw.get("contact_ids") or []
    roles = raw.get("contact_roles") or []
    if not isinstance(contact_ids, list) or not isinstance(roles, list):
        raise ValidationFailed("contact_ids and contact_roles must be lists")
    try:
        contact_ids = list(dict.fromkeys(str(uuid.UUID(str(c))) for c in contact_ids))
    except ValueError:
        raise ValidationFailed("contact_ids must be contact ids") from None
    if not all(isinstance(r, str) and r.strip() and len(r) <= 80 for r in roles):
        raise ValidationFailed("contact_roles must be non-empty labels")
    roles = list(dict.fromkeys(r.strip().casefold() for r in roles))
    if not contact_ids and not roles:
        raise ValidationFailed("name at least one contact id or contact role")
    if len(contact_ids) + len(roles) > 50:
        raise ValidationFailed("at most 50 recipients per notify action")
    return {"type": "notify", "channels": channels, "contact_ids": contact_ids, "contact_roles": roles}


def _validate_work_order(raw: dict) -> dict:
    extra = set(raw) - {"type", "title", "description", "priority", "due_in_hours", "assignee_contact_id"}
    if extra:
        raise ValidationFailed(f"unknown keys: {sorted(extra)}")
    item: dict[str, Any] = {
        "type": "create_work_order",
        "title": validate_template(raw.get("title"), field="title", max_length=300),
    }
    if raw.get("description") is not None:
        item["description"] = validate_template(raw["description"], field="description", max_length=4000)
    try:
        item["priority"] = WorkOrderPriority(raw.get("priority", "normal")).value
    except ValueError:
        raise ValidationFailed(f"priority must be one of {[p.value for p in WorkOrderPriority]}") from None
    due = raw.get("due_in_hours")
    if due is not None:
        if not _is_number(due) or not 0 < due <= 24 * 365:
            raise ValidationFailed("due_in_hours must be between 0 and 8760")
        item["due_in_hours"] = due
    assignee = raw.get("assignee_contact_id")
    if assignee is not None:
        try:
            item["assignee_contact_id"] = str(uuid.UUID(str(assignee)))
        except ValueError:
            raise ValidationFailed("assignee_contact_id must be a contact id") from None
    return item


def referenced_contact_ids(actions: list[dict]) -> set[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    for action in actions:
        if action["type"] == "notify":
            ids.update(uuid.UUID(c) for c in action["contact_ids"])
        elif action["type"] == "create_work_order" and action.get("assignee_contact_id"):
            ids.add(uuid.UUID(action["assignee_contact_id"]))
    return ids


# ---------------------------------------------------------------- evaluation


def build_context(
    *,
    severity: str,
    event_type_key: str,
    source_type: str,
    occurred_at: datetime,
    timezone: str,
    attributes: dict[str, Any],
    site: dict[str, Any] | None,
    asset: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flatten an event into the field names conditions refer to."""
    try:
        local = occurred_at.astimezone(ZoneInfo(timezone))
    except Exception:
        local = occurred_at
    values: dict[str, Any] = {
        "severity": severity,
        "event_type": event_type_key,
        "source.type": source_type,
        "local_hour": local.hour,
        "local_weekday": local.weekday(),
    }
    if site:
        values.update({"site.code": site.get("code"), "site.kind": site.get("kind"), "site.name": site.get("name")})
    if asset:
        values.update(
            {
                "asset.code": asset.get("code"),
                "asset.type": asset.get("type"),
                "asset.name": asset.get("name"),
                "asset.criticality": asset.get("criticality"),
            }
        )
    for key, value in attributes.items():
        values[f"attributes.{key}"] = value
    return values


def evaluate(conditions: list[dict], match: str, values: dict[str, Any]) -> bool:
    if not conditions:
        return True
    results = (_safe_check(c, values) for c in conditions)
    return any(results) if match == "any" else all(results)


def _safe_check(condition: dict, values: dict[str, Any]) -> bool:
    try:
        return _check(condition, values)
    except Exception:
        return False


def _norm(value: Any) -> Any:
    return value.casefold() if isinstance(value, str) else value


def _equal(actual: Any, expected: Any) -> bool:
    # True == 1 in Python; for rules a boolean only equals a boolean.
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual is expected
    if _is_number(actual) and _is_number(expected):
        return float(actual) == float(expected)
    if isinstance(actual, str) and isinstance(expected, str):
        return _norm(actual) == _norm(expected)
    return False


def _check(condition: dict, values: dict[str, Any]) -> bool:
    field, op = condition["field"], condition["op"]
    actual = values.get(field)
    present = actual is not None and actual != ""

    if op == "exists":
        return present
    if op == "not_exists":
        return not present
    if not present:
        return False  # missing data never triggers a rule

    expected = condition.get("value")
    if field == "severity":
        actual_rank = SEVERITY_RANK[Severity(actual)]
        if op in _ORDER_OPS:
            return _compare(actual_rank, op, SEVERITY_RANK[Severity(expected)])
        if op in _LIST_OPS:
            hit = any(Severity(v) == Severity(actual) for v in expected)
            return hit if op == "in" else not hit

    if op == "eq":
        return _equal(actual, expected)
    if op == "ne":
        return not _equal(actual, expected)
    if op == "in":
        return any(_equal(actual, v) for v in expected)
    if op == "not_in":
        return not any(_equal(actual, v) for v in expected)
    if op == "contains":
        if isinstance(actual, str):
            return isinstance(expected, str) and _norm(expected) in _norm(actual)
        return False
    if op in _ORDER_OPS:
        if not (_is_number(actual) and _is_number(expected)):
            return False
        return _compare(actual, op, expected)
    return False


def _compare(actual: float, op: str, expected: float) -> bool:
    return {
        "gt": actual > expected,
        "gte": actual >= expected,
        "lt": actual < expected,
        "lte": actual <= expected,
    }[op]


def validate_match(match: Any) -> str:
    if match not in ("all", "any"):
        raise ValidationFailed("match must be 'all' or 'any'.")
    return match
