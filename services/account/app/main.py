import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from app.api import accounts, health, transactions
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.service_name)
    log = get_logger("startup")
    await init_db()
    log.info("service_started", port=settings.port)
    yield
    log.info("service_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Account Service",
        version=settings.version,
        lifespan=lifespan,
    )

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
    app.include_router(transactions.router)
    app.include_router(accounts.router)

    configure_tracing(app)
    return app


app = create_app()
