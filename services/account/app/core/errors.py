from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace

from app.core.logging import get_logger

logger = get_logger(__name__)


class LedgerError(Exception):
    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class ValidationError(LedgerError):
    code = "VALIDATION_ERROR"
    status_code = 400


def _current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None


def _envelope(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "traceId": _current_trace_id()}},
    )


async def ledger_error_handler(_: Request, exc: LedgerError) -> JSONResponse:
    logger.warning("ledger_error", code=exc.code, message=exc.message, status_code=exc.status_code)
    return _envelope(exc.code, exc.message, exc.status_code)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    logger.warning("request_validation_error", detail=detail)
    return _envelope("VALIDATION_ERROR", detail, 400)


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", error=str(exc))
    return _envelope("INTERNAL_ERROR", "An unexpected error occurred", 500)
