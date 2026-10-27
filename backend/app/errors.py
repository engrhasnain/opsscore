"""Application errors and the single JSON error envelope every response uses.

    {"error": {"code": "NOT_FOUND", "message": "...", "details": ..., "request_id": "..."}}

Codes are stable and machine-readable; messages are for people.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.request_context import current_request_id

logger = logging.getLogger("opscore.errors")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_FAILED"


class Unauthorized(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class TooManyRequests(AppError):
    status_code = 429
    code = "RATE_LIMITED"

    def __init__(self, message: str, *, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class PayloadTooLarge(AppError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"


class UpstreamFailed(AppError):
    status_code = 502
    code = "UPSTREAM_FAILED"


def _envelope(status: int, code: str, message: str, details: Any = None, headers=None):
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": current_request_id(),
        }
    }
    return JSONResponse(status_code=status, content=body, headers=headers)


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        headers = None
        if isinstance(exc, TooManyRequests):
            headers = {"Retry-After": str(exc.retry_after)}
        if isinstance(exc, Unauthorized):
            headers = {"WWW-Authenticate": "Bearer"}
        return _envelope(exc.status_code, exc.code, exc.message, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        details = [
            {
                "location": [str(part) for part in err.get("loc", ())],
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return _envelope(422, "VALIDATION_FAILED", "The request is not valid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").title()
        return _envelope(exc.status_code, code, message, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        logger.exception("unhandled error", exc_info=exc)
        return _envelope(500, "INTERNAL_ERROR", "Something went wrong. Quote the request id.")
