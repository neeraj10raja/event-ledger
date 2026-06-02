import json

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.repository import AuditRepository

logger = get_logger("audit")


def _trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None


async def write_audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    event_id: str | None = None,
    details: dict | None = None,
) -> None:
    payload = json.dumps(details, default=str) if details else None
    trace_id = _trace_id()
    await AuditRepository(session).write(
        event_id=event_id,
        action=action,
        actor=actor,
        trace_id=trace_id,
        details=payload,
    )
    logger.info(
        "audit",
        audit=True,
        actor=actor,
        action=action,
        event_id=event_id,
        details=details,
    )
