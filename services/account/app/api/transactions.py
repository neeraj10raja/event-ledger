from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import transaction_apply_duration_seconds
from app.db.session import get_session
from app.schemas.transaction import TransactionApplied, TransactionIn
from app.services.ledger_service import LedgerService

router = APIRouter(tags=["transactions"])


@router.post(
    "/accounts/{account_id}/transactions",
    response_model=TransactionApplied,
    response_model_by_alias=True,
)
async def apply_transaction(
    account_id: str,
    payload: TransactionIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TransactionApplied:
    with transaction_apply_duration_seconds.time():
        result, inserted = await LedgerService(session).apply(account_id, payload)
        response.status_code = 201 if inserted else 200
        return result
