from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.transaction import AccountView, BalanceView
from app.services.ledger_service import LedgerService

router = APIRouter(tags=["accounts"])


@router.get(
    "/accounts/{account_id}/balance",
    response_model=BalanceView,
    response_model_by_alias=True,
)
async def get_balance(account_id: str, session: AsyncSession = Depends(get_session)) -> BalanceView:
    return await LedgerService(session).get_balance(account_id)


@router.get(
    "/accounts/{account_id}",
    response_model=AccountView,
    response_model_by_alias=True,
)
async def get_account(account_id: str, session: AsyncSession = Depends(get_session)) -> AccountView:
    return await LedgerService(session).get_account(account_id)
