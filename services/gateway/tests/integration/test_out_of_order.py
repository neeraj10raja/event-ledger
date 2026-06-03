import pytest


def evt(eid, ts, type_="CREDIT", amount="10.00") -> dict:
    return {
        "eventId": eid,
        "accountId": "acct-ooo",
        "type": type_,
        "amount": amount,
        "currency": "USD",
        "eventTimestamp": ts,
    }


@pytest.mark.asyncio
async def test_listing_is_chronological_regardless_of_arrival(client):
    # Arrival order: later, earlier, middle. Listing must be chronological.
    arrivals = [
        evt("late", "2026-05-20T10:00:00Z"),
        evt("early", "2026-05-10T10:00:00Z"),
        evt("middle", "2026-05-15T10:00:00Z"),
    ]
    for e in arrivals:
        r = await client.post("/events", json=e)
        assert r.status_code == 201

    r = await client.get("/events?account=acct-ooo")
    items = r.json()["items"]
    assert [i["eventId"] for i in items] == ["early", "middle", "late"]


@pytest.mark.asyncio
async def test_out_of_order_does_not_affect_apply_calls(client, fake_account):
    """All three events are still apply()ed in arrival order; ordering is a read concern."""
    await client.post("/events", json=evt("late", "2026-05-20T10:00:00Z"))
    await client.post("/events", json=evt("early", "2026-05-10T10:00:00Z"))
    assert [c["event_id"] for c in fake_account.calls] == ["late", "early"]


@pytest.mark.asyncio
async def test_listing_chronological_with_mixed_timezone_offsets(client):
    """Same instant can be expressed with different offsets; UTC normalization
    means listings sort by real chronology, not by raw string."""
    # All three represent strictly increasing UTC moments, but the offsets vary
    # so a naive lexical sort on the input strings would put them in the wrong order.
    arrivals = [
        evt("us-east", "2026-05-15T11:00:00-05:00"),   # = 16:00 UTC
        evt("utc-z",   "2026-05-15T15:00:00Z"),         # = 15:00 UTC
        evt("ist",     "2026-05-15T22:30:00+05:30"),    # = 17:00 UTC
    ]
    for e in arrivals:
        r = await client.post("/events", json=e)
        assert r.status_code == 201

    r = await client.get("/events?account=acct-ooo")
    items = r.json()["items"]
    assert [i["eventId"] for i in items] == ["utc-z", "us-east", "ist"]
