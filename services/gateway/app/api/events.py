from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import LedgerError
from app.core.metrics import event_processing_duration_seconds
from app.db.session import get_session
from app.resilience.rate_limit import limiter
from app.schemas.event import EventIn, EventListOut, EventOut
from app.services.account_client import AccountClient
from app.services.event_service import EventService

router = APIRouter(tags=["events"])


def get_account_client(request: Request) -> AccountClient:
    return request.app.state.account_client


@router.post(
    "/events",
    response_model=EventOut,
    response_model_by_alias=True,
)
@limiter.limit(lambda: f"{get_settings().rate_limit_per_minute}/minute")
async def post_event(
    request: Request,
    payload: EventIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
    account: AccountClient = Depends(get_account_client),
) -> EventOut:
    with event_processing_duration_seconds.labels(endpoint="POST /events").time():
        result = await EventService(session, account).ingest(payload)
        response.status_code = result.http_status
        return result.event_out


@router.get(
    "/events/{event_id}",
    response_model=EventOut,
    response_model_by_alias=True,
)
async def get_event(
    event_id: str,
    session: AsyncSession = Depends(get_session),
    account: AccountClient = Depends(get_account_client),
) -> EventOut:
    event = await EventService(session, account).get_event(event_id)
    if event is None:
        raise LedgerError("Event not found", code="EVENT_NOT_FOUND", status_code=404)
    return event


@router.get(
    "/events",
    response_model=EventListOut,
    response_model_by_alias=True,
)
async def list_events(
    account: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    account_client: AccountClient = Depends(get_account_client),
) -> EventListOut:
    items, total = await EventService(session, account_client).list_events(account, limit=limit, offset=offset)
    return EventListOut(items=items, total=total)
