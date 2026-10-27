"""Small, reusable input normalizers shared by services and the CSV importer."""

import re
from zoneinfo import ZoneInfo, available_timezones

from app.errors import ValidationFailed

_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
_KEY = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_KIND = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
_PHONE_SEPARATORS = re.compile(r"[\s().-]")

_ZONES: frozenset[str] | None = None


def code(value: str, *, field: str = "code") -> str:
    """Site and asset codes: case-insensitive, stored upper-case ("fdp-14" == "FDP-14")."""
    normalized = (value or "").strip().upper()
    if not _CODE.match(normalized):
        raise ValidationFailed(
            f"{field} must be 1-64 characters: letters, digits, '.', '_' or '-'.",
            details={"field": field, "value": value},
        )
    return normalized


def key(value: str, *, field: str = "key") -> str:
    normalized = (value or "").strip().lower()
    if not _KEY.match(normalized):
        raise ValidationFailed(
            f"{field} must start with a letter and use lowercase letters, digits, '_' or '.'.",
            details={"field": field, "value": value},
        )
    return normalized


def slug(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not _SLUG.match(normalized):
        raise ValidationFailed("slug must be lowercase letters, digits and '-', max 63.")
    return normalized


def kind(value: str | None, *, default: str = "site") -> str:
    normalized = (value or default).strip().lower().replace(" ", "_").replace("-", "_")
    if not _KIND.match(normalized):
        raise ValidationFailed("kind must be lowercase letters, digits and '_'.")
    return normalized


def phone(value: str | None, *, field: str = "phone") -> str | None:
    """Accept common human formats, store E.164 ("+1 (713) 555-0100" -> "+17135550100")."""
    if value is None or not str(value).strip():
        return None
    normalized = _PHONE_SEPARATORS.sub("", str(value).strip())
    if normalized.startswith("00"):
        normalized = "+" + normalized[2:]
    if not _E164.match(normalized):
        raise ValidationFailed(
            f"{field} must be an international number, e.g. +5491155550100.",
            details={"field": field, "value": value},
        )
    return normalized


def timezone(value: str | None, *, field: str = "timezone", required: bool = False) -> str | None:
    global _ZONES
    if value is None or not str(value).strip():
        if required:
            raise ValidationFailed(f"{field} is required.")
        return None
    value = str(value).strip()
    if _ZONES is None:
        _ZONES = frozenset(available_timezones())
    if value not in _ZONES:
        raise ValidationFailed(
            f"{field} must be an IANA time zone such as America/Argentina/Buenos_Aires.",
            details={"field": field, "value": value},
        )
    ZoneInfo(value)  # loads the zone; fails loudly if tz data is missing
    return value


def text(value: str | None, *, field: str, max_length: int, required: bool = True) -> str | None:
    if value is None or not str(value).strip():
        if required:
            raise ValidationFailed(f"{field} must not be empty.")
        return None
    value = str(value).strip()
    if len(value) > max_length:
        raise ValidationFailed(f"{field} must be at most {max_length} characters.")
    return value


def coordinate(value, *, field: str, low: float, high: float) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationFailed(f"{field} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationFailed(f"{field} must be a number.") from None
    if number != number or not low <= number <= high:
        raise ValidationFailed(f"{field} must be between {low} and {high}.")
    return number
