from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.metrics import render
from app.db.session import get_session
from app.resilience.circuit_breaker import account_breaker
from app.services.account_client import AccountClient

router = APIRouter(tags=["ops"])


def _breaker_label() -> str:
    return account_breaker.state.value


@router.get("/health")
async def health(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    account_client: AccountClient = request.app.state.account_client
    account_ok = await account_client.health()
    overall = "ok" if db_ok and account_ok else "degraded"
    return {
        "status": overall,
        "service": settings.service_name,
        "version": settings.version,
        "checks": {
            "db": "ok" if db_ok else "error",
            "account_service": "ok" if account_ok else "unreachable",
        },
        "circuitBreaker": _breaker_label(),
    }


@router.get("/metrics")
async def metrics() -> Response:
    body, content_type = render()
    return Response(content=body, media_type=content_type)
