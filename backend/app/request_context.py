"""Per-request correlation id, available to logging, errors and the audit log."""

import re
import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def current_request_id() -> str | None:
    return _request_id.get()


def accept_or_generate(incoming: str | None) -> str:
    """Trust a caller's id only if it is short and plain, otherwise mint one.

    Unchecked ids end up in logs and audit rows, so they are an injection path.
    """
    if incoming and _VALID_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex


def bind(request_id: str):
    return _request_id.set(request_id)


def reset(token) -> None:
    _request_id.reset(token)
