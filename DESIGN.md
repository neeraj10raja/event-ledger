# Event Ledger — Design Document

## 1. Problem

Build two cooperating microservices that ingest financial transaction events from upstream systems that are not perfectly synchronized. Events may arrive **out of order** and **more than once**. The system must remain correct under those conditions and degrade gracefully when one component is unavailable.

## 2. Architecture

![architecture](diagrams/architecture.mmd)

> *Rendered Mermaid sources live under `docs/diagrams/`. They render directly on GitHub.*

| Service | Role | Storage |
|---|---|---|
| **Event Gateway** (`:8000`, public) | Validates input, enforces idempotency, persists events, calls the Account Service, exposes read APIs that work even when the Account Service is down. | SQLite — `events`, `outbox`, `audit_log` |
| **Account Service** (`:8001`, internal) | Applies idempotent transactions and computes balances. | SQLite — `transactions`, `audit_log` |

The two services **do not share a database** and communicate only via synchronous REST. The Gateway is the source of truth for **events**; the Account Service is the source of truth for **balances**.

## 3. API Contracts

### Event Gateway

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| `POST` | `/events` | event payload | `201` on new, `200` on idempotent replay, `503` when Account Service unavailable (event queued), `4xx` on validation |
| `GET` | `/events/{id}` | — | `200` event, `404` not found |
| `GET` | `/events?account={id}` | query param | `200` list ordered by `eventTimestamp` ASC |
| `GET` | `/health` | — | `200` status object |
| `GET` | `/metrics` | — | Prometheus exposition |

### Account Service

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| `POST` | `/accounts/{id}/transactions` | `{eventId, type, amount, currency, eventTimestamp}` | `201` on new, `200` on idempotent replay, `4xx` on validation |
| `GET` | `/accounts/{id}/balance` | — | `200 {accountId, balance, currency}` |
| `GET` | `/accounts/{id}` | — | `200 {accountId, balance, recentTransactions[]}` |
| `GET` | `/health` | — | `200` status object |
| `GET` | `/metrics` | — | Prometheus exposition |

Event payload validation rules (Pydantic):
- `eventId` non-empty string
- `accountId` non-empty string
- `type ∈ {"CREDIT","DEBIT"}`
- `amount > 0` (Decimal, stored as string)
- `currency` non-empty string
- `eventTimestamp` ISO-8601
- `metadata` optional object

## 4. Sequence — `POST /events`

![sequence](diagrams/post-events-sequence.mmd)

The Gateway always persists locally **first**, *then* calls the Account Service. This separation gives us:

1. **Idempotency for free** — the `event_id` PK rejects duplicates.
2. **Graceful degradation** — local reads work even when the Account Service is down.
3. **Durability** — a queued event is safe across Gateway restarts.

## 5. Event State Machine

![states](diagrams/event-state-machine.mmd)

| State | Meaning |
|---|---|
| `RECEIVED` | Validated and persisted; not yet acknowledged by Account Service. |
| `APPLIED` | Account Service confirmed application. |
| `QUEUED` | Persisted, but Account Service unavailable/timeout/CB-open; will be retried by the outbox replayer. |
| `FAILED` | Permanent rejection (e.g. Account Service returned 4xx). |

## 6. Resiliency

The Gateway → Account call is wrapped in three layered patterns. Composition matters: each handles a different failure mode.

| Pattern | Tool | Configuration | Failure mode addressed |
|---|---|---|---|
| **Timeout** | `httpx.Timeout(2.0, connect=0.5)` | hard ceiling per attempt | hung / slow downstream |
| **Retry with exponential backoff + jitter** | `tenacity` | 3 attempts, 100 ms → 1.5 s, full jitter | transient network blips, 5xx |
| **Circuit breaker** | `app/resilience/circuit_breaker.py` (in-house async) | `fail_max=5`, `reset_timeout=30s` | sustained downstream failure |

**Order of composition (outer → inner):** `circuit_breaker( retry( one_http_call ) )`.

- Each Gateway request consumes **one** "breaker attempt." Inner retries do *not* inflate the failure counter, so a brief blip won't trip the breaker but a sustained outage will.
- HTTP 4xx is treated as a **permanent** failure: no retry, no breaker count, immediate surface to the client.
- Breaker state changes update the `circuit_breaker_state` Prometheus gauge and emit a structured `circuit_breaker_state_change` log line.

**Why an in-house breaker rather than `pybreaker`?** `pybreaker.call_async` is implemented via Tornado's `@gen.coroutine` and does not track failures in `await`ed asyncio calls — failed coroutines never reach the failure counter, so the breaker effectively never opens under asyncio. The in-house implementation (~100 lines) handles CLOSED → OPEN → HALF_OPEN → CLOSED transitions correctly for asyncio and is fully unit-tested in `services/gateway/tests/unit/test_circuit_breaker.py`.

### Async fallback queue (outbox)

When the breaker is open or retries are exhausted, the event is stored in the `outbox` table with state `QUEUED`. A background asyncio task polls every 5 seconds, calls the Account Service for each queued event, and on success transitions it to `APPLIED`. Idempotency at both layers makes replay safe.

### Rate limiting

`slowapi` limits `POST /events` to 100 req/min/IP. Configurable via env.

## 7. Graceful Degradation

| Endpoint | Behavior when Account Service is down |
|---|---|
| `POST /events` | Persist locally, return **503** with `{status: "QUEUED"}` |
| `GET /events/{id}` | Works — reads only Gateway DB |
| `GET /events?account=…` | Works — reads only Gateway DB |
| `GET /health` | Reports `degraded` with details |

## 8. Observability

### Distributed Tracing

- **OpenTelemetry SDK** with the OTLP/HTTP exporter pointed at the OTel Collector.
- FastAPI and HTTPX auto-instrumentation produce server and client spans.
- W3C **`traceparent`** is the propagation format — set automatically by the HTTPX instrumentation, so the Gateway → Account call is one continuous trace.
- Jaeger UI at `http://localhost:16686` for visualization.

### Structured Logging

- `structlog` emitting JSON.
- Every log line carries `timestamp`, `level`, `service`, `trace_id`, `span_id`, `event`, plus event-specific fields.
- Request middleware logs every HTTP request with `method`, `path`, `status`, `duration_ms`.

### Metrics

Custom Prometheus metrics (exposed on `/metrics`):

| Name | Type | Labels |
|---|---|---|
| `events_received_total` | counter | `type`, `result` |
| `events_applied_total` | counter | `type` |
| `event_processing_duration_seconds` | histogram | `endpoint` |
| `account_client_duration_seconds` | histogram | `outcome` |
| `circuit_breaker_state` | gauge | — (0=closed, 1=half-open, 2=open) |
| `outbox_depth` | gauge | — |

### Audit Log

A first-class `audit_log` table on both services records every state transition with `event_id`, `action`, `actor`, `trace_id`, `details_json`, `created_at`. Actions:

```
RECEIVED · DEDUPED · APPLIED · FAILED · QUEUED · REPLAYED ·
CB_OPENED · CB_CLOSED · RATE_LIMITED
```

The same record is mirrored as a structured log line tagged `audit=true` so log-aggregation systems can capture it without scraping the DB.

## 9. Error Handling

A small exception hierarchy lets each layer raise meaningfully and a global handler map them to HTTP responses:

```
LedgerError
├── ValidationError              -> 400
├── DuplicateEventError          -> 200 (idempotent)
├── AccountServiceClientError    -> 4xx (relayed)
└── AccountServiceUnavailableError -> 503
```

All error responses follow the same envelope:

```json
{"error": {"code": "ACCOUNT_SERVICE_UNAVAILABLE", "message": "…", "traceId": "…"}}
```

Stack traces are logged with `logger.exception(...)` but never returned to clients.

## 10. Why these choices

- **SQLite over Postgres** — handout requires an embedded DB; SQLite per service satisfies "no shared DB" with zero infra.
- **FastAPI over Flask** — native async, Pydantic validation, automatic OpenAPI.
- **Composed resiliency** vs. one-of — demonstrates depth and clear failure-mode separation; each pattern has a single, testable responsibility.
- **Outbox queue** even though only `at-least-one resiliency pattern` is required — turns 503s into eventual successes and is the realistic production pattern; small code, large operational win.
- **Mermaid for diagrams** — version-controlled, renders on GitHub, no binary blobs in the repo.

## 11. Trade-offs and non-goals

- Balance is computed by aggregating transactions on demand. Fine for the assignment; in production we'd materialize per-account balances with triggers or a cache.
- No authentication / authorization — out of scope per the handout.
- No multi-currency conversion — `currency` is treated as opaque.
- The Outbox replayer is a single in-process task. In a multi-replica deployment we'd add a row-level lock (`SELECT … FOR UPDATE SKIP LOCKED`) or move replay to a dedicated worker. Out of scope here.
