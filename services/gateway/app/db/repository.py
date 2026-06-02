from typing import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Event, OutboxEntry


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, event_id: str) -> Event | None:
        return await self.session.get(Event, event_id)

    async def add(self, event: Event) -> None:
        self.session.add(event)
        await self.session.flush()

    async def update_status(self, event_id: str, status: str) -> None:
        event = await self.session.get(Event, event_id)
        if event:
            event.status = status

    async def list_by_account(
        self, account_id: str, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Event]:
        stmt = (
            select(Event)
            .where(Event.account_id == account_id)
            .order_by(Event.event_timestamp.asc())
            .offset(offset)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def count_by_account(self, account_id: str) -> int:
        stmt = select(func.count()).select_from(Event).where(Event.account_id == account_id)
        return (await self.session.execute(stmt)).scalar_one()


class OutboxRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue(self, event_id: str, last_error: str | None) -> None:
        existing = await self.session.get(OutboxEntry, event_id)
        if existing:
            existing.attempts += 1
            existing.last_error = last_error
        else:
            self.session.add(OutboxEntry(event_id=event_id, last_error=last_error))

    async def list_pending(self, limit: int = 50) -> Sequence[OutboxEntry]:
        stmt = select(OutboxEntry).order_by(OutboxEntry.queued_at.asc()).limit(limit)
        return (await self.session.execute(stmt)).scalars().all()

    async def remove(self, event_id: str) -> None:
        await self.session.execute(delete(OutboxEntry).where(OutboxEntry.event_id == event_id))

    async def record_attempt(self, event_id: str, last_error: str | None) -> None:
        existing = await self.session.get(OutboxEntry, event_id)
        if existing:
            existing.attempts += 1
            existing.last_error = last_error

    async def depth(self) -> int:
        return (await self.session.execute(select(func.count()).select_from(OutboxEntry))).scalar_one()


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def write(self, *, event_id: str | None, action: str, actor: str, trace_id: str | None, details: str | None = None) -> None:
        self.session.add(AuditLog(event_id=event_id, action=action, actor=actor, trace_id=trace_id, details=details))
