from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.errors import AccountServiceClientError, AccountServiceUnavailableError
from app.resilience.circuit_breaker import reset_breaker
from app.resilience.retry import TransientHttpError
from app.services.account_client import AccountClient


@pytest.fixture(autouse=True)
def _reset_breaker():
    reset_breaker()
    yield
    reset_breaker()


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failures(monkeypatch):
    client = AccountClient(base_url="http://fake")
    attempts = {"n": 0}

    async def flaky(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TransientHttpError("503")
        return {"ok": True}

    monkeypatch.setattr(client, "_one_call", flaky)
    result = await client.apply_transaction(
        "acct", event_id="e1", type_="CREDIT",
        amount=1, currency="USD", event_timestamp="2026-05-15T14:02:11Z",
    )
    assert result == {"ok": True}
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_retry_gives_up_and_raises_unavailable(monkeypatch):
    client = AccountClient(base_url="http://fake")

    async def always_fail(*args, **kwargs):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(client, "_one_call", always_fail)
    with pytest.raises(AccountServiceUnavailableError):
        await client.apply_transaction(
            "acct", event_id="e1", type_="CREDIT",
            amount=1, currency="USD", event_timestamp="2026-05-15T14:02:11Z",
        )


@pytest.mark.asyncio
async def test_4xx_is_not_retried(monkeypatch):
    client = AccountClient(base_url="http://fake")
    calls = {"n": 0}

    async def bad_request(*args, **kwargs):
        calls["n"] += 1
        raise AccountServiceClientError("invalid", status_code=400)

    monkeypatch.setattr(client, "_one_call", bad_request)
    with pytest.raises(AccountServiceClientError):
        await client.apply_transaction(
            "acct", event_id="e1", type_="CREDIT",
            amount=1, currency="USD", event_timestamp="2026-05-15T14:02:11Z",
        )
    assert calls["n"] == 1, "4xx should not be retried"


@pytest.mark.asyncio
async def test_repeated_failures_trip_the_breaker(monkeypatch):
    """Each gateway request consumes exactly one breaker attempt (retries inside)."""
    from app.resilience.circuit_breaker import account_breaker, State

    client = AccountClient(base_url="http://fake")

    async def always_fail(*args, **kwargs):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(client, "_one_call", always_fail)
    # default breaker fail_max=5
    for _ in range(5):
        with pytest.raises(AccountServiceUnavailableError):
            await client.apply_transaction(
                "acct", event_id="e1", type_="CREDIT",
                amount=1, currency="USD", event_timestamp="2026-05-15T14:02:11Z",
            )
    assert account_breaker.state == State.OPEN
