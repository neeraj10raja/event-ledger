"""Direct proof that W3C traceparent reaches the Account Service over HTTP.

The OTel HTTPX instrumentation is configured at app startup and injects
traceparent into every outbound request when a span is active. This test
captures the real outbound HTTP via respx so we can assert on the header
that would actually be sent across the wire — independent of the
FakeAccountClient used in most integration tests.
"""
import httpx
import pytest
import respx
from opentelemetry import trace

from app.resilience.circuit_breaker import reset_breaker
from app.services.account_client import AccountClient


@pytest.fixture(autouse=True)
def _reset_cb():
    reset_breaker()
    yield
    reset_breaker()


@pytest.mark.asyncio
@respx.mock
async def test_traceparent_header_sent_to_account_service():
    captured: list[dict[str, str]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(dict(request.headers))
        return httpx.Response(
            201,
            json={"eventId": "e1", "accountId": "acct-tp", "balance": "1.00"},
        )

    respx.post("http://fake-acct/accounts/acct-tp/transactions").mock(side_effect=capture)

    client = AccountClient(base_url="http://fake-acct")
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("client-request") as span:
        expected_trace_id = format(span.get_span_context().trace_id, "032x")
        await client.apply_transaction(
            "acct-tp", event_id="e1", type_="CREDIT",
            amount=1, currency="USD", event_timestamp="2026-05-15T14:02:11Z",
        )
    await client.aclose()

    assert captured, "no outbound request captured"
    headers = captured[0]
    assert "traceparent" in headers, f"traceparent missing; got: {list(headers)}"
    # W3C traceparent format: 00-<trace_id-32 hex>-<span_id-16 hex>-<flags-2 hex>
    parts = headers["traceparent"].split("-")
    assert len(parts) == 4 and parts[0] == "00"
    assert parts[1] == expected_trace_id, "trace_id in header must match the active span"
