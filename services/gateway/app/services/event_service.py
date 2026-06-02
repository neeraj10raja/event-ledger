import json
from datetime import datetime, timezone
from decimal import Decimal

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.audit import write_audit
from app.core.config import get_settings
from app.core.errors import AccountServiceClientError, AccountServiceUnavailableError
from app.core.logging import get_logger
from app.core.metrics import events_applied_total, events_received_total
from app.db.models import Event
from app.db.repository import EventRepository, OutboxRepository
from app.schemas.event import EventIn, EventOut
from app.services.account_client import AccountClient

logger = get_logger("event_service")


def _to_out(event: Event) -> EventOut:
    return EventOut(
        eventId=event.event_id,
        accountId=event.account_id,
        type=event.type,
        amount=Decimal(event.amount),
        currency=event.currency,
        eventTimestamp=event.event_timestamp,
        metadata=json.loads(event.metadata_json) if event.metadata_json else None,
        status=event.status,
        receivedAt=event.received_at,
        traceId=event.trace_id,
    )


class IngestResult:
    """Captures both the persisted event and the status code the API should return."""

    def __init__(self, event_out: EventOut, http_status: int):
        self.event_out = event_out
        self.http_status = http_status


class EventService:
    def __init__(self, session: AsyncSession, account_client: AccountClient):
        self.session = session
        self.events = EventRepository(session)
        self.outbox = OutboxRepository(session)
        self.account = account_client
        self.actor = get_settings().service_name

    async def ingest(self, payload: EventIn) -> IngestResult:
        existing = await self.events.get(payload.event_id)
        if existing is not None:
            await write_audit(
                self.session,
                actor=self.actor,
                action="DEDUPED",
                event_id=payload.event_id,
                details={"status": existing.status},
            )
            events_received_total.labels(type=payload.type, result="duplicate").inc()
            await self.session.commit()
            status_map = {"APPLIED": 200, "QUEUED": 202, "RECEIVED": 202, "FAILED": 200}
            return IngestResult(_to_out(existing), status_map.get(existing.status, 200))

        ctx = trace.get_current_span().get_span_context()
        trace_id = format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None

        event = Event(
            event_id=payload.event_id,
            account_id=payload.account_id,
            type=payload.type,
            amount=str(payload.amount),
            currency=payload.currency,
            event_timestamp=payload.event_timestamp.isoformat(),
            metadata_json=json.dumps(payload.metadata) if payload.metadata else None,
            status="RECEIVED",
            received_at=datetime.now(timezone.utc),
            trace_id=trace_id,
        )
        await self.events.add(event)
        await write_audit(
            self.session,
            actor=self.actor,
            action="RECEIVED",
            event_id=event.event_id,
            details={"accountId": event.account_id, "type": event.type, "amount": event.amount},
        )

        try:
            await self.account.apply_transaction(
                event.account_id,
                event_id=event.event_id,
                type_=event.type,
                amount=Decimal(event.amount),
                currency=event.currency,
                event_timestamp=event.event_timestamp,
            )
        except AccountServiceUnavailableError as exc:
            event.status = "QUEUED"
            await self.outbox.enqueue(event.event_id, last_error=str(exc))
            await write_audit(
                self.session,
                actor=self.actor,
                action="QUEUED",
                event_id=event.event_id,
                details={"reason": str(exc)},
            )
            events_received_total.labels(type=event.type, result="queued").inc()
            await self.session.commit()
            return IngestResult(_to_out(event), 503)
        except AccountServiceClientError as exc:
            event.status = "FAILED"
            await write_audit(
                self.session,
                actor=self.actor,
                action="FAILED",
                event_id=event.event_id,
                details={"reason": str(exc), "status": exc.status_code},
            )
            events_received_total.labels(type=event.type, result="rejected").inc()
            await self.session.commit()
            raise

        event.status = "APPLIED"
        await write_audit(
            self.session,
            actor=self.actor,
            action="APPLIED",
            event_id=event.event_id,
            details={"accountId": event.account_id},
        )
        events_received_total.labels(type=event.type, result="accepted").inc()
        events_applied_total.labels(type=event.type).inc()
        await self.session.commit()
        return IngestResult(_to_out(event), 201)

    async def get_event(self, event_id: str) -> EventOut | None:
        event = await self.events.get(event_id)
        return _to_out(event) if event else None

    async def list_events(self, account_id: str, *, limit: int, offset: int) -> tuple[list[EventOut], int]:
        items = await self.events.list_by_account(account_id, limit=limit, offset=offset)
        total = await self.events.count_by_account(account_id)
        return [_to_out(e) for e in items], total
