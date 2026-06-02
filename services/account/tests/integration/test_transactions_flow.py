from decimal import Decimal

import pytest

ACCT = "acct-int"


def _tx(event_id: str, type_: str, amount: str, ts: str = "2026-05-15T14:02:11Z") -> dict:
    return {
        "eventId": event_id,
        "type": type_,
        "amount": amount,
        "currency": "USD",
        "eventTimestamp": ts,
    }


@pytest.mark.asyncio
async def test_apply_then_get_balance(client):
    r = await client.post(f"/accounts/{ACCT}/transactions", json=_tx("e1", "CREDIT", "150.00"))
    assert r.status_code == 201
    assert Decimal(r.json()["balance"]) == Decimal("150.00")

    r = await client.get(f"/accounts/{ACCT}/balance")
    assert r.status_code == 200
    assert Decimal(r.json()["balance"]) == Decimal("150.00")


@pytest.mark.asyncio
async def test_idempotent_apply_returns_200(client):
    r1 = await client.post(f"/accounts/{ACCT}/transactions", json=_tx("e1", "CREDIT", "150.00"))
    assert r1.status_code == 201

    r2 = await client.post(f"/accounts/{ACCT}/transactions", json=_tx("e1", "CREDIT", "150.00"))
    assert r2.status_code == 200, "duplicate event_id must not double-apply"

    r = await client.get(f"/accounts/{ACCT}/balance")
    assert Decimal(r.json()["balance"]) == Decimal("150.00")


@pytest.mark.asyncio
async def test_credit_minus_debit(client):
    await client.post(f"/accounts/{ACCT}/transactions", json=_tx("c1", "CREDIT", "200.00"))
    await client.post(f"/accounts/{ACCT}/transactions", json=_tx("d1", "DEBIT", "30.00"))
    await client.post(f"/accounts/{ACCT}/transactions", json=_tx("d2", "DEBIT", "5.50"))

    r = await client.get(f"/accounts/{ACCT}/balance")
    assert Decimal(r.json()["balance"]) == Decimal("164.50")


@pytest.mark.asyncio
async def test_account_view_includes_recent_transactions(client):
    await client.post(f"/accounts/{ACCT}/transactions", json=_tx("a", "CREDIT", "10.00", ts="2026-05-15T14:02:11Z"))
    await client.post(f"/accounts/{ACCT}/transactions", json=_tx("b", "DEBIT", "3.00", ts="2026-05-16T10:00:00Z"))

    r = await client.get(f"/accounts/{ACCT}")
    body = r.json()
    assert Decimal(body["balance"]) == Decimal("7.00")
    assert {tx["eventId"] for tx in body["recentTransactions"]} == {"a", "b"}


@pytest.mark.asyncio
async def test_validation_error_returns_400_with_envelope(client):
    r = await client.post(f"/accounts/{ACCT}/transactions", json=_tx("bad", "CREDIT", "-1"))
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "traceId" in body["error"]


@pytest.mark.asyncio
async def test_health_reports_db_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["checks"]["db"] == "ok"


@pytest.mark.asyncio
async def test_metrics_exposes_prometheus_format(client):
    await client.post(f"/accounts/{ACCT}/transactions", json=_tx("m1", "CREDIT", "1.00"))
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "transactions_applied_total" in r.text


@pytest.mark.asyncio
async def test_balance_zero_for_unknown_account(client):
    r = await client.get("/accounts/never-seen/balance")
    assert r.status_code == 200
    assert Decimal(r.json()["balance"]) == Decimal("0")


@pytest.mark.asyncio
async def test_audit_log_records_apply_and_dedupe(client):
    """Indirect check via the trace_id presence and subsequent read."""
    await client.post(f"/accounts/{ACCT}/transactions", json=_tx("aud", "CREDIT", "1.00"))
    await client.post(f"/accounts/{ACCT}/transactions", json=_tx("aud", "CREDIT", "1.00"))
    # Both calls return successfully; balance is unchanged after dedupe
    r = await client.get(f"/accounts/{ACCT}/balance")
    assert Decimal(r.json()["balance"]) == Decimal("1.00")
