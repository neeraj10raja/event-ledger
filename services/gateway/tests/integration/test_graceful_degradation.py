import httpx
import pytest

from app.core.errors import AccountServiceUnavailableError


def evt(eid: str = "e1") -> dict:
    return {
        "eventId": eid,
        "accountId": "acct-deg",
        "type": "CREDIT",
        "amount": "10.00",
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
    }


@pytest.mark.asyncio
async def test_post_returns_503_with_queued_status_when_account_down(client, fake_account):
    fake_account.fail_with(httpx.ConnectError("down"))

    r = await client.post("/events", json=evt())
    assert r.status_code == 503
    assert r.json()["status"] == "QUEUED"


@pytest.mark.asyncio
async def test_local_reads_still_work_when_account_down(client, fake_account):
    # First, persist an event with the downstream working.
    r = await client.post("/events", json=evt("ok-1"))
    assert r.status_code == 201

    # Then take the downstream offline. Local reads must still succeed.
    fake_account.fail_with(httpx.ConnectError("down"))
    fake_account.healthy = False

    r1 = await client.get("/events/ok-1")
    assert r1.status_code == 200
    assert r1.json()["eventId"] == "ok-1"

    r2 = await client.get("/events?account=acct-deg")
    assert r2.status_code == 200
    assert r2.json()["total"] == 1


@pytest.mark.asyncio
async def test_health_reports_degraded_when_account_unreachable(client, fake_account):
    fake_account.healthy = False
    r = await client.get("/health")
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["account_service"] == "unreachable"
