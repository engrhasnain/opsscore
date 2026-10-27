"""Placeholder templates for alert and work order text, e.g. "Inspect {asset.name}".

Deliberately not ``str.format``: format strings can reach object attributes
(``{0.__class__}``), which is unsafe for text clients type into a settings page.
Only the placeholders listed here are recognised.
"""

import re

from app.errors import ValidationFailed

_PLACEHOLDER = re.compile(r"\{([a-z_]+(?:\.[a-z][a-z0-9_]*)?)\}")
_FIXED = {
    "event_type",
    "severity",
    "occurred_at",
    "site.code",
    "site.name",
    "asset.code",
    "asset.name",
}


_ANY_BRACES = re.compile(r"\{([^{}]*)\}")


def placeholders(template: str) -> list[str]:
    """Everything written in braces, valid or not, so typos are reported."""
    return _ANY_BRACES.findall(template)


def validate_template(template: str, *, field: str, max_length: int) -> str:
    if not isinstance(template, str) or not template.strip():
        raise ValidationFailed(f"{field} must not be empty.")
    template = template.strip()
    if len(template) > max_length:
        raise ValidationFailed(f"{field} must be at most {max_length} characters.")
    unknown = [
        p
        for p in placeholders(template)
        if not _PLACEHOLDER.fullmatch("{" + p + "}") or (p not in _FIXED and not p.startswith("attributes."))
    ]
    if unknown:
        raise ValidationFailed(
            f"{field} uses unknown placeholders.",
            details={"unknown": unknown, "allowed": [*sorted(_FIXED), "attributes.<name>"]},
        )
    return template


def render(template: str, values: dict[str, str], *, max_length: int | None = None) -> str:
    """Fill placeholders. Missing values render as an em dash, never as the raw token."""

    def _sub(match: re.Match) -> str:
        value = values.get(match.group(1))
        return "—" if value in (None, "") else str(value)

    text = _PLACEHOLDER.sub(_sub, template)
    if max_length is not None and len(text) > max_length:
        text = text[: max_length - 1] + "…"
    return text
