import pytest


def evt(eid: str) -> dict:
    return {
        "eventId": eid,
        "accountId": "acct-i",
        "type": "CREDIT",
        "amount": "100.00",
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
    }


@pytest.mark.asyncio
async def test_same_event_twice_returns_200_and_no_double_apply(client, fake_account):
    r1 = await client.post("/events", json=evt("e1"))
    assert r1.status_code == 201
    assert fake_account.calls == [{"account_id": "acct-i", "event_id": "e1", "type": "CREDIT", "amount": "100.00"}]

    r2 = await client.post("/events", json=evt("e1"))
    assert r2.status_code == 200, "duplicate must return 200"
    assert r2.json()["status"] == "APPLIED"
    assert len(fake_account.calls) == 1, "downstream must not be called for a duplicate"


@pytest.mark.asyncio
async def test_listing_unaffected_by_duplicate(client):
    await client.post("/events", json=evt("e1"))
    await client.post("/events", json=evt("e1"))
    await client.post("/events", json=evt("e1"))

    r = await client.get("/events?account=acct-i")
    assert r.json()["total"] == 1
