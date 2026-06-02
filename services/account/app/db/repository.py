from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Transaction


class TransactionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert_if_absent(self, tx: Transaction) -> tuple[Transaction, bool]:
        """Returns (transaction, inserted). inserted=False means duplicate."""
        stmt = (
            sqlite_insert(Transaction)
            .values(
                event_id=tx.event_id,
                account_id=tx.account_id,
                type=tx.type,
                amount=tx.amount,
                currency=tx.currency,
                event_timestamp=tx.event_timestamp,
                applied_at=tx.applied_at,
                trace_id=tx.trace_id,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        result = await self.session.execute(stmt)
        inserted = result.rowcount == 1
        existing = await self.session.get(Transaction, tx.event_id)
        return existing or tx, inserted

    async def get(self, event_id: str) -> Transaction | None:
        return await self.session.get(Transaction, event_id)

    async def list_by_account(self, account_id: str, limit: int = 50) -> Sequence[Transaction]:
        stmt = (
            select(Transaction)
            .where(Transaction.account_id == account_id)
            .order_by(Transaction.event_timestamp.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def balance(self, account_id: str) -> Decimal:
        # SQLite stores amount as TEXT for Decimal safety. Sum in app code to avoid float drift.
        stmt = select(Transaction.type, Transaction.amount).where(Transaction.account_id == account_id)
        rows = (await self.session.execute(stmt)).all()
        total = Decimal("0")
        for ttype, amount in rows:
            value = Decimal(str(amount))
            total += value if ttype == "CREDIT" else -value
        return total

    async def currency_for(self, account_id: str) -> str | None:
        stmt = select(Transaction.currency).where(Transaction.account_id == account_id).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def write(self, *, event_id: str | None, action: str, actor: str, trace_id: str | None, details: str | None = None) -> None:
        self.session.add(AuditLog(event_id=event_id, action=action, actor=actor, trace_id=trace_id, details=details))
