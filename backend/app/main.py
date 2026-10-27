"""The FastAPI application."""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__, request_context
from app.api.routes import assistant, auth, catalog, operations, organization
from app.config import get_settings
from app.db import get_engine
from app.errors import install_error_handlers
from app.logging_config import configure_logging
from app.ratelimit import RateLimiter

logger = logging.getLogger("opscore.http")

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="OpsCore API",
        version=__version__,
        description=(
            "Multi-tenant event, alert and evidence platform for oil & gas and maritime "
            "operations. Every endpoint except /health and /auth/login needs a bearer token "
            "(people) or an X-API-Key header (devices and integrations)."
        ),
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    app.state.login_limiter = RateLimiter(settings.login_attempts_per_minute)
    app.state.inbound_limiter = RateLimiter(settings.inbound_requests_per_minute)
    app.state.sender_limiter = RateLimiter(20)  # one sender cannot run up the bill

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key", "Idempotency-Key", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request_context.accept_or_generate(request.headers.get("x-request-id"))
        token = request_context.bind(request_id)
        started = time.perf_counter()
        # On an unhandled error the id is left bound on purpose, so the 500
        # handler (which runs outside this middleware) can still quote it.
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        request_context.reset(token)
        return response

    install_error_handlers(app)

    for router in (
        auth.router,
        organization.platform,
        organization.router,
        catalog.router,
        operations.router,
        assistant.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    @app.get("/health/live", tags=["health"])
    def live() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/health/ready", tags=["health"])
    def ready():
        try:
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            logger.exception("database not reachable")
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ok"}

    return app


app = create_app()
