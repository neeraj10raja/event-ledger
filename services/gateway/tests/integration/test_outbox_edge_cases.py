import pytest

from app.core.errors import AccountServiceClientError
from app.services.outbox_replayer import OutboxReplayer


def evt(eid: str) -> dict:
    return {
        "eventId": eid,
        "accountId": "acct-edge",
        "type": "CREDIT",
        "amount": "1.00",
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
    }


@pytest.mark.asyncio
async def test_replayer_marks_failed_on_permanent_4xx(client, fake_account):
    import httpx

    # First, queue an event by having the downstream temporarily down.
    fake_account.fail_with(httpx.ConnectError("down"))
    await client.post("/events", json=evt("perm"))

    # Now the downstream is up but will reject this event permanently.
    fake_account.fail_with(AccountServiceClientError("nope", status_code=422))

    replayer = OutboxReplayer(fake_account)
    drained = await replayer.drain_once()
    assert drained == 0

    listing = (await client.get("/events?account=acct-edge")).json()
    assert listing["items"][0]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_post_event_4xx_from_downstream_marks_failed(client, fake_account):
    fake_account.fail_with(AccountServiceClientError("invalid", status_code=422))

    r = await client.post("/events", json=evt("f1"))
    assert r.status_code == 422
    listing = (await client.get("/events?account=acct-edge")).json()
    assert listing["items"][0]["status"] == "FAILED"
