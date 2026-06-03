# Event Ledger

A two-microservice Python implementation of the Schwab take-home: a public **Event Gateway** that ingests financial transaction events with idempotency, out-of-order tolerance, distributed tracing, structured logging, layered resiliency, and graceful degradation; and an internal **Account Service** that holds the source of truth for balances.

- **DESIGN.md** — full design document with diagrams.
- **docs/api-contracts.md** — request/response shapes.
- **docs/functional-coverage.md** — requirement → test mapping.
- **docs/coverage/** — pre-generated HTML coverage reports.
- **docs/ai-workflow.md** — how AI tools were used across SDLC phases.

---

## Architecture (TL;DR)

```
Client ──► Event Gateway (8000) ──► Account Service (8001)
            sqlite (events)         sqlite (transactions)
                │                         │
                └────► OTel Collector ───► Jaeger UI (16686)
                └────► /metrics ◄──── Prometheus (9090)
```

- **Gateway** owns the durable event ledger and orchestrates the apply call.
- **Account** owns the balance, idempotent at the persistence layer.
- They share no database.

See [DESIGN.md](DESIGN.md) for the sequence diagram, event state machine, and the full rationale.

---

## Quickstart

### With Docker Compose (preferred)

```bash
docker compose up --build
```

Then in another terminal:

```bash
./scripts/smoke.sh
```

URLs:
- Gateway: <http://localhost:8000> (OpenAPI: `/docs`)
- Account: <http://localhost:8001> (OpenAPI: `/docs`)
- Jaeger UI: <http://localhost:16686>
- Prometheus: <http://localhost:9090>

Shut down with `docker compose down`. Volumes (`gateway-data`, `account-data`) persist between runs; add `-v` to wipe state.

### Without Docker (local Python)

```bash
python3.11 -m venv .venv && source .venv/bin/activate

# Runtime only (matches what the Docker images bake in):
pip install -r services/gateway/requirements.txt -r services/account/requirements.txt

# To also run the test suites and coverage:
pip install -r services/gateway/requirements-dev.txt -r services/account/requirements-dev.txt
```

In one terminal:
```bash
(cd services/account && uvicorn app.main:app --port 8001)
```

In another:
```bash
(cd services/gateway && ACCOUNT_SERVICE_URL=http://localhost:8001 \
  uvicorn app.main:app --port 8000)
```

---

## Running the Tests

Install test dependencies first (see above), then:

```bash
./scripts/run-coverage.sh
```

Output:
- HTML report: `docs/coverage/gateway/index.html`, `docs/coverage/account/index.html`
- coverage.xml beside the HTML for CI ingest
- Terminal summary

Without coverage:

```bash
(cd services/gateway && pytest)
(cd services/account && pytest)
```

Current results: **62 tests, 100 % passing**, line coverage **94 % (gateway) / 96 % (account)**.

The mapping from each handout requirement to the tests that prove it is in `docs/functional-coverage.md`.

---

## Resiliency

The Gateway → Account call composes three patterns; each addresses a different failure mode.

| Layer | Library / Code | Defaults | Purpose |
|---|---|---|---|
| Timeout | `httpx.Timeout(2.0s, connect=0.5s)` | per attempt | Bound time spent on slow downstream |
| Retry with exponential backoff + jitter | `tenacity` | 3 attempts, 0.1 → 1.5 s | Smooth over transient blips and 5xx |
| Circuit breaker | `app/resilience/circuit_breaker.py` (async-native) | `fail_max=5`, `reset_timeout=30s` | Stop hammering a downed downstream |

Composition order: **`circuit_breaker( retry( one_http_call ) )`** — each end-to-end request consumes exactly one breaker attempt; inner retries don't inflate the failure counter.

**Why this composition?** Each pattern alone handles a single failure mode; only together do they cover the realistic spectrum of downstream failures (slow / blip / sustained outage). The breaker also gives a clean "fail fast" path that surfaces as a 503 to the client and prevents request-queue exhaustion.

**Why an in-house breaker?** `pybreaker`'s async support is via a Tornado `@gen.coroutine` path that doesn't track asyncio failures — failed `await`s never reach the failure counter, so the breaker would never open. The in-house implementation is ~100 lines and fully unit-tested in `tests/unit/test_circuit_breaker.py`.

**Async fallback queue (outbox)** — when a request hits 503, the event is durably stored with status `QUEUED`. A background asyncio task drains the outbox every 5 s by re-invoking the same resilient client. Idempotency at both layers makes replay safe.

---

## Graceful Degradation

| Endpoint | Account up | Account down |
|---|---|---|
| `POST /events` | 201 (APPLIED) | 503 (QUEUED) — durable |
| `GET /events/{id}` | 200 | 200 — local read |
| `GET /events?account=…` | 200 | 200 — local read |
| `GET /accounts/{id}/balance` | 200 | 503 — Account is source of truth |
| `GET /health` | `status: ok` | `status: degraded` |

---

## Deployment Notes

- **Account Service port (8001) exposure** — The handout describes the Account Service as internal, called only by the Gateway. The compose file publishes 8001 to the host for demo / walkthrough convenience (so you can curl `/health`, browse `/docs`, and run the smoke script). In a real deployment this port would be cluster-internal — remove the `ports:` mapping from the `account` service and rely on Docker's internal DNS (`http://account:8001`).
- **Uvicorn access/startup logs are plain text** — Application logs (everything the services emit via `structlog`) are JSON with trace IDs. The lines Uvicorn writes itself ("Started server process", access logs at INFO) are plain text, which is the default Uvicorn behavior. Two ways to make them JSON in production: wire `structlog.stdlib.ProcessorFormatter` into the `uvicorn`/`uvicorn.access` loggers, or run behind a sidecar (Fluent Bit / Vector) that normalizes to JSON. Out of scope for this submission.

## Observability

- **Tracing:** OpenTelemetry SDK → OTel Collector → Jaeger. W3C `traceparent` propagated by the HTTPX instrumentation, so one trace spans both services. Every log line is stamped with the current `trace_id`.
- **Logging:** `structlog` JSON. Fields: `timestamp`, `level`, `service`, `trace_id`, `span_id`, `event`, plus event-specific kwargs.
- **Metrics:** Prometheus `/metrics` on both services. Notable series:
  - `events_received_total{type,result}`
  - `events_applied_total{type}`
  - `event_processing_duration_seconds`
  - `account_client_duration_seconds{outcome}`
  - `circuit_breaker_state` (0=closed, 1=half-open, 2=open)
  - `outbox_depth`
- **Audit:** First-class `audit_log` table on both services capturing every transition (RECEIVED, DEDUPED, APPLIED, FAILED, QUEUED, REPLAYED, …) with `actor`, `trace_id`, and `details`. Same record is mirrored as a `audit=true` log line.

---

## Configuration

All configuration is environment-driven via `pydantic-settings`. Key knobs:

| Variable | Default | Service |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/{svc}.db` | both |
| `ACCOUNT_SERVICE_URL` | `http://localhost:8001` | gateway |
| `ACCOUNT_CALL_TIMEOUT_SECONDS` | `2.0` | gateway |
| `RETRY_ATTEMPTS` | `3` | gateway |
| `BREAKER_FAIL_MAX` | `5` | gateway |
| `BREAKER_RESET_TIMEOUT_SECONDS` | `30` | gateway |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `5.0` | gateway |
| `RATE_LIMIT_PER_MINUTE` | `100` | gateway |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | both |

---

## AI-Augmented SDLC

This project was built using Claude Code as an AI pair programmer across the design, development, and QA phases. See [docs/ai-workflow.md](docs/ai-workflow.md) for the full breakdown — which agents were used, for what, and what the human reviewer kept in the loop.

---

## Repository Layout

```
event-ledger/
├── DESIGN.md
├── README.md
├── docker-compose.yml
├── docs/
│   ├── api-contracts.md
│   ├── ai-workflow.md
│   ├── functional-coverage.md
│   ├── coverage/
│   └── diagrams/
├── infra/                          # prometheus.yml, otel-collector.yaml
├── scripts/
│   ├── smoke.sh
│   └── run-coverage.sh
└── services/
    ├── gateway/    (FastAPI, ~13 modules + tests)
    └── account/    (FastAPI, ~9 modules + tests)
```

---

## Submission Notes

Commit history is preserved (no squash); each commit explains the *why* alongside the *what*. Run `git log --oneline` for the full sequence.
