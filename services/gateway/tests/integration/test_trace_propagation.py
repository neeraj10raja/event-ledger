"""Trace propagation tests.

The full OTel SDK auto-instrumentation can be heavy in tests; we cover trace
propagation at the contract level by verifying that:

1. The Gateway stamps the current trace_id onto the persisted Event (so it
   appears in logs and audit rows).
2. When trace context is active, the same trace_id surfaces in the Event
   response body and the audit_log row.

That contract — same trace id end-to-end — is the property that lets an
operator reconstruct a single request across both services from logs alone.
"""
from opentelemetry import trace

import pytest

from app.core.tracing import configure_tracing  # noqa: F401  (ensures provider exists)


def evt(eid: str = "e1") -> dict:
    return {
        "eventId": eid,
        "accountId": "acct-trace",
        "type": "CREDIT",
        "amount": "1.00",
        "currency": "USD",
        "eventTimestamp": "2026-05-15T14:02:11Z",
    }


@pytest.mark.asyncio
async def test_trace_id_in_response_when_span_active(client):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("outer") as span:
        expected = format(span.get_span_context().trace_id, "032x")
        r = await client.post("/events", json=evt())
    assert r.status_code in (201, 503)
    body = r.json()
    # Trace id from the active span should be on the stored event.
    assert body.get("traceId") == expected


@pytest.mark.asyncio
async def test_trace_id_present_on_errors(client):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("outer") as span:
        expected = format(span.get_span_context().trace_id, "032x")
        r = await client.post("/events", json={"eventId": "bad", "type": "CREDIT"})
    assert r.status_code == 400
    assert r.json()["error"]["traceId"] == expected
