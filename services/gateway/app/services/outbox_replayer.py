import asyncio
import json
from decimal import Decimal

from app.audit.audit import write_audit
from app.core.config import get_settings
from app.core.errors import AccountServiceClientError, AccountServiceUnavailableError
from app.core.logging import get_logger
from app.core.metrics import events_applied_total, outbox_depth
from app.db.repository import EventRepository, OutboxRepository
from app.db import session as session_mod
from app.services.account_client import AccountClient

logger = get_logger("outbox_replayer")


class OutboxReplayer:
    def __init__(self, account_client: AccountClient):
        self.account = account_client
        self.actor = get_settings().service_name
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        s = get_settings()
        if not s.outbox_enabled:
            logger.info("outbox_disabled")
            return
        self._task = asyncio.create_task(self._run(s.outbox_poll_interval_seconds))
        logger.info("outbox_started", interval_s=s.outbox_poll_interval_seconds)

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run(self, interval: float) -> None:
        while not self._stop_event.is_set():
            try:
                await self.drain_once()
            except Exception as exc:  # never let the loop die
                logger.exception("outbox_loop_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def drain_once(self) -> int:
        """Attempt to replay all pending entries. Returns count successfully replayed."""
        replayed = 0
        async with session_mod.SessionLocal() as session:
            outbox = OutboxRepository(session)
            events = EventRepository(session)
            pending = await outbox.list_pending(limit=50)
            outbox_depth.set(len(pending))
            for entry in pending:
                event = await events.get(entry.event_id)
                if event is None:
                    await outbox.remove(entry.event_id)
                    continue
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
                    await outbox.record_attempt(entry.event_id, str(exc))
                    logger.info("outbox_replay_deferred", event_id=entry.event_id, reason=str(exc))
                    continue
                except AccountServiceClientError as exc:
                    event.status = "FAILED"
                    await outbox.remove(entry.event_id)
                    await write_audit(
                        session,
                        actor=self.actor,
                        action="FAILED",
                        event_id=event.event_id,
                        details={"reason": str(exc), "status": exc.status_code, "source": "replay"},
                    )
                    logger.warning("outbox_replay_failed_permanent", event_id=entry.event_id)
                    continue
                event.status = "APPLIED"
                await outbox.remove(entry.event_id)
                await write_audit(
                    session,
                    actor=self.actor,
                    action="REPLAYED",
                    event_id=event.event_id,
                    details=json.loads('{"source":"outbox"}'),
                )
                events_applied_total.labels(type=event.type).inc()
                replayed += 1
            await session.commit()
            outbox_depth.set(await outbox.depth())
        if replayed:
            logger.info("outbox_drained", count=replayed)
        return replayed
