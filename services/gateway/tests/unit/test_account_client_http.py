"""Tests exercising the real HTTP code path of AccountClient.

Most integration tests use the FakeAccountClient (overrides _one_call) so we
test resiliency without binding to httpx. These tests use respx to mock the
network layer instead, exercising the genuine httpx call, status-code
handling, and health probe.
"""
import httpx
import pytest
import respx

from app.core.errors import AccountServiceClientError, AccountServiceUnavailableError
from app.resilience.circuit_breaker import reset_breaker
from app.services.account_client import AccountClient


@pytest.fixture(autouse=True)
def _reset():
    reset_breaker()
    yield
    reset_breaker()


@pytest.mark.asyncio
@respx.mock
async def test_real_http_success_path():
    route = respx.post("http://fake/accounts/acct-1/transactions").mock(
        return_value=httpx.Response(201, json={"eventId": "e1", "accountId": "acct-1", "balance": "10.00"})
    )
    client = AccountClient(base_url="http://fake")
    result = await client.apply_transaction(
        "acct-1", event_id="e1", type_="CREDIT", amount=10, currency="USD", event_timestamp="2026-05-15T14:02:11Z",
    )
    assert route.called
    assert result["balance"] == "10.00"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_real_http_4xx_maps_to_client_error():
    respx.post("http://fake/accounts/acct-1/transactions").mock(
        return_value=httpx.Response(400, json={"error": {"code": "VALIDATION_ERROR"}})
    )
    client = AccountClient(base_url="http://fake")
    with pytest.raises(AccountServiceClientError):
        await client.apply_transaction(
            "acct-1", event_id="e1", type_="CREDIT", amount=10, currency="USD", event_timestamp="2026-05-15T14:02:11Z",
        )
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_real_http_5xx_retries_then_surfaces():
    respx.post("http://fake/accounts/acct-1/transactions").mock(
        return_value=httpx.Response(503, json={"error": {"code": "x"}})
    )
    client = AccountClient(base_url="http://fake")
    with pytest.raises(AccountServiceUnavailableError):
        await client.apply_transaction(
            "acct-1", event_id="e1", type_="CREDIT", amount=10, currency="USD", event_timestamp="2026-05-15T14:02:11Z",
        )
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_health_probe_returns_true_on_200():
    respx.get("http://fake/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    client = AccountClient(base_url="http://fake")
    assert await client.health() is True
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_health_probe_returns_false_on_failure():
    respx.get("http://fake/health").mock(side_effect=httpx.ConnectError("nope"))
    client = AccountClient(base_url="http://fake")
    assert await client.health() is False
    await client.aclose()
