import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api import events, health
from app.core.config import get_settings
from app.core.errors import (
    LedgerError,
    ledger_error_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging, get_logger
from app.core.tracing import configure_tracing
from app.db.session import init_db
from app.resilience.rate_limit import limiter
from app.services.account_client import AccountClient
from app.services.outbox_replayer import OutboxReplayer


def _trace_id_str() -> str | None:
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None


async def rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMITED",
                "message": f"Rate limit exceeded: {exc.detail}",
                "traceId": _trace_id_str(),
            }
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.service_name)
    log = get_logger("startup")
    await init_db()

    app.state.account_client = AccountClient()
    app.state.replayer = OutboxReplayer(app.state.account_client)
    await app.state.replayer.start()

    log.info("service_started", port=settings.port, account_url=settings.account_service_url)
    yield
    await app.state.replayer.stop()
    await app.state.account_client.aclose()
    log.info("service_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Event Gateway",
        version=settings.version,
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(LedgerError, ledger_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        log = get_logger("http")
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response

    app.include_router(health.router)
    app.include_router(events.router)

    configure_tracing(app)
    return app


app = create_app()
