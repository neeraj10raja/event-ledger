from datetime import datetime, timezone

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.audit import write_audit
from app.core.config import get_settings
from app.core.metrics import transactions_applied_total
from app.db.models import Transaction
from app.db.repository import TransactionRepository
from app.schemas.transaction import AccountView, BalanceView, TransactionApplied, TransactionIn, TransactionView


class LedgerService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.txns = TransactionRepository(session)
        self.actor = get_settings().service_name

    async def apply(self, account_id: str, payload: TransactionIn) -> tuple[TransactionApplied, bool]:
        ctx = trace.get_current_span().get_span_context()
        trace_id = format(ctx.trace_id, "032x") if ctx and ctx.is_valid else None

        tx = Transaction(
            event_id=payload.event_id,
            account_id=account_id,
            type=payload.type,
            amount=str(payload.amount),
            currency=payload.currency,
            event_timestamp=payload.event_timestamp.isoformat(),
            applied_at=datetime.now(timezone.utc),
            trace_id=trace_id,
        )
        stored, inserted = await self.txns.insert_if_absent(tx)

        action = "APPLIED" if inserted else "DEDUPED"
        await write_audit(
            self.session,
            actor=self.actor,
            action=action,
            event_id=payload.event_id,
            details={"accountId": account_id, "type": payload.type, "amount": str(payload.amount)},
        )
        transactions_applied_total.labels(type=payload.type, result=action.lower()).inc()

        balance = await self.txns.balance(account_id)
        await self.session.commit()

        return TransactionApplied(
            eventId=stored.event_id,
            accountId=stored.account_id,
            balance=balance,
            currency=stored.currency,
            appliedAt=stored.applied_at,
        ), inserted

    async def get_balance(self, account_id: str) -> BalanceView:
        balance = await self.txns.balance(account_id)
        currency = await self.txns.currency_for(account_id) or "USD"
        return BalanceView(accountId=account_id, balance=balance, currency=currency)

    async def get_account(self, account_id: str) -> AccountView:
        balance = await self.txns.balance(account_id)
        currency = await self.txns.currency_for(account_id) or "USD"
        recent = await self.txns.list_by_account(account_id, limit=50)
        return AccountView(
            accountId=account_id,
            balance=balance,
            currency=currency,
            recentTransactions=[
                TransactionView(
                    eventId=t.event_id,
                    type=t.type,
                    amount=t.amount,
                    currency=t.currency,
                    eventTimestamp=t.event_timestamp,
                )
                for t in recent
            ],
        )
