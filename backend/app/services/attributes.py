"""Event attribute schemas, defined per event type by each client.

A schema is a list of field definitions:

    {"name": "ppm", "type": "number", "required": true, "unit": "ppm", "min": 0}

Declared fields are type-checked. Undeclared fields are kept but reported as
warnings: rejecting a safety event because a device sent one extra field
would lose evidence, which is worse than storing an unexpected key.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.errors import ValidationFailed
from app.units import is_known_unit

ATTR_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ATTR_TYPES = {"string", "number", "integer", "boolean"}
MAX_SCHEMA_FIELDS = 50
MAX_ATTRIBUTES = 50
MAX_STRING = 2000
MAX_ENUM = 50
_DEFINITION_KEYS = {"name", "type", "required", "unit", "enum", "min", "max", "max_length", "label"}


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def validate_schema(schema: Any) -> list[dict]:
    """Check a schema definition and return it normalized. Raises ValidationFailed."""
    if not isinstance(schema, list):
        raise ValidationFailed("attributes_schema must be a list.")
    if len(schema) > MAX_SCHEMA_FIELDS:
        raise ValidationFailed(f"attributes_schema allows at most {MAX_SCHEMA_FIELDS} fields.")

    problems: list[dict] = []
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(schema):
        where = f"attributes_schema[{index}]"
        if not isinstance(raw, dict):
            problems.append({"field": where, "message": "must be an object"})
            continue
        unknown = set(raw) - _DEFINITION_KEYS
        if unknown:
            problems.append({"field": where, "message": f"unknown keys: {sorted(unknown)}"})
        name, kind = raw.get("name"), raw.get("type")
        if not isinstance(name, str) or not ATTR_NAME.match(name):
            problems.append({"field": f"{where}.name", "message": "use lowercase letters, digits and _"})
            continue
        if name in seen:
            problems.append({"field": f"{where}.name", "message": f"duplicate field {name!r}"})
            continue
        seen.add(name)
        if kind not in ATTR_TYPES:
            problems.append({"field": f"{where}.type", "message": f"must be one of {sorted(ATTR_TYPES)}"})
            continue

        item: dict[str, Any] = {"name": name, "type": kind, "required": bool(raw.get("required", False))}
        if isinstance(raw.get("label"), str) and raw["label"].strip():
            item["label"] = raw["label"].strip()[:120]

        if "unit" in raw:
            unit = raw["unit"]
            if kind not in ("number", "integer"):
                problems.append({"field": f"{where}.unit", "message": "only numbers have units"})
            elif not isinstance(unit, str) or not is_known_unit(unit):
                problems.append({"field": f"{where}.unit", "message": f"unknown unit {unit!r}"})
            else:
                item["unit"] = unit

        if "enum" in raw:
            choices = raw["enum"]
            if kind != "string":
                problems.append({"field": f"{where}.enum", "message": "only strings can have choices"})
            elif (
                not isinstance(choices, list)
                or not 1 <= len(choices) <= MAX_ENUM
                or not all(isinstance(c, str) and c for c in choices)
                or len(set(choices)) != len(choices)
            ):
                problems.append({"field": f"{where}.enum", "message": f"must be 1-{MAX_ENUM} distinct strings"})
            else:
                item["enum"] = choices

        for bound in ("min", "max"):
            if bound in raw:
                if kind not in ("number", "integer") or not _is_number(raw[bound]):
                    problems.append({"field": f"{where}.{bound}", "message": "must be a number"})
                else:
                    item[bound] = raw[bound]
        if "min" in item and "max" in item and item["min"] > item["max"]:
            problems.append({"field": where, "message": "min is greater than max"})

        if "max_length" in raw:
            limit = raw["max_length"]
            if kind != "string" or not isinstance(limit, int) or not 1 <= limit <= MAX_STRING:
                problems.append({"field": f"{where}.max_length", "message": f"must be 1-{MAX_STRING}"})
            else:
                item["max_length"] = limit
        normalized.append(item)

    if problems:
        raise ValidationFailed("attributes_schema is not valid.", details=problems)
    return normalized


@dataclass
class AttributeCheck:
    values: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def validate_values(schema: list[dict], values: Any) -> AttributeCheck:
    """Check event attributes against the schema. Raises ValidationFailed."""
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ValidationFailed("attributes must be an object.")
    if len(values) > MAX_ATTRIBUTES:
        raise ValidationFailed(f"At most {MAX_ATTRIBUTES} attributes are allowed.")

    by_name = {item["name"]: item for item in schema}
    problems: list[dict] = []
    clean: dict[str, Any] = {}
    warnings: list[str] = []

    for key, value in values.items():
        if not isinstance(key, str) or not ATTR_NAME.match(key):
            problems.append({"field": f"attributes.{key}", "message": "names use lowercase letters, digits and _"})
            continue
        if value is None:
            continue  # null means "not reported"
        if isinstance(value, dict | list):
            problems.append({"field": f"attributes.{key}", "message": "must be a single value"})
            continue
        if isinstance(value, str) and len(value) > MAX_STRING:
            problems.append({"field": f"attributes.{key}", "message": f"longer than {MAX_STRING} characters"})
            continue
        if isinstance(value, float) and not math.isfinite(value):
            problems.append({"field": f"attributes.{key}", "message": "must be a finite number"})
            continue

        definition = by_name.get(key)
        if definition is None:
            warnings.append(f"attribute {key!r} is not declared for this event type")
            clean[key] = value
            continue
        problem = _check_value(definition, value)
        if problem:
            problems.append({"field": f"attributes.{key}", "message": problem})
            continue
        if definition["type"] == "integer" and isinstance(value, float):
            value = int(value)
        clean[key] = value

    for item in schema:
        if item.get("required") and item["name"] not in clean:
            problems.append({"field": f"attributes.{item['name']}", "message": "is required"})

    if problems:
        raise ValidationFailed("Event attributes are not valid.", details=problems)
    return AttributeCheck(values=clean, warnings=warnings)


def _check_value(definition: dict, value: Any) -> str | None:
    kind = definition["type"]
    if kind == "string":
        if not isinstance(value, str):
            return "must be text"
        if "enum" in definition and value not in definition["enum"]:
            return f"must be one of {definition['enum']}"
        if "max_length" in definition and len(value) > definition["max_length"]:
            return f"longer than {definition['max_length']} characters"
        return None
    if kind == "boolean":
        return None if isinstance(value, bool) else "must be true or false"
    if not _is_number(value):
        return "must be a number"
    if kind == "integer" and not float(value).is_integer():
        return "must be a whole number"
    if "min" in definition and value < definition["min"]:
        return f"must be at least {definition['min']}"
    if "max" in definition and value > definition["max"]:
        return f"must be at most {definition['max']}"
    return None
