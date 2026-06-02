import httpx
import pytest

from app.services.outbox_replayer import OutboxReplayer


def evt(eid: str) -> dict:
    return {
        "eventId": eid,
        "accountId": "acct-out",
        "type": "CREDIT",
        "amount": "5.00",
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
    }


@pytest.mark.asyncio
async def test_outbox_drains_after_account_recovers(client, fake_account):
    # Phase 1: account is down, events are queued.
    fake_account.fail_with(httpx.ConnectError("down"))
    for i in range(3):
        r = await client.post("/events", json=evt(f"o-{i}"))
        assert r.status_code == 503

    listing = (await client.get("/events?account=acct-out")).json()
    statuses = {i["eventId"]: i["status"] for i in listing["items"]}
    assert statuses == {"o-0": "QUEUED", "o-1": "QUEUED", "o-2": "QUEUED"}

    # Phase 2: account recovers. Replayer drains the outbox.
    fake_account.fail_with(None)
    replayer = OutboxReplayer(fake_account)
    drained = await replayer.drain_once()
    assert drained == 3

    listing = (await client.get("/events?account=acct-out")).json()
    statuses = {i["eventId"]: i["status"] for i in listing["items"]}
    assert statuses == {"o-0": "APPLIED", "o-1": "APPLIED", "o-2": "APPLIED"}


@pytest.mark.asyncio
async def test_replayer_leaves_entries_when_still_down(client, fake_account):
    fake_account.fail_with(httpx.ConnectError("down"))
    await client.post("/events", json=evt("q-1"))

    # Drain attempt while still failing.
    replayer = OutboxReplayer(fake_account)
    drained = await replayer.drain_once()
    assert drained == 0

    listing = (await client.get("/events?account=acct-out")).json()
    assert listing["items"][0]["status"] == "QUEUED"
