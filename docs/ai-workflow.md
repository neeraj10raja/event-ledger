# AI-Augmented SDLC Workflow

This take-home was built with **Claude Code** (Anthropic's CLI agent for Claude Opus 4.7) as the primary pair-programmer. The objective wasn't "have the AI write everything" — it was to mirror a realistic engineering workflow where the human stays in the loop on design decisions, while the AI accelerates research, scaffolding, and mechanical work.

Below is the breakdown by SDLC phase, in the same shape as the deliverables Suresh outlined.

## Design Agent

**What it did**
- Read the candidate handout and the follow-up email, surfacing the implicit requirements (e.g., the "AI-augmented evaluation" framing).
- Proposed three resiliency choices (single pattern vs. combined) and three observability stacks, presenting trade-offs.
- Drafted the full design plan with explicit non-goals so scope creep was visible up-front.
- Produced architecture, sequence, and state-machine diagrams in Mermaid (committed as source so they render on GitHub without binary blobs).

**What I kept in the loop on**
- Resiliency composition order (`circuit_breaker( retry( one_call ) )` vs. inverted).
- Whether to include the Jaeger + OTel Collector stack vs. just trace IDs in logs.
- Bonus feature scope (we agreed to include three: Prometheus metrics, async fallback queue, rate limiting). Pact-style contract tests were planned but descoped during implementation — `pact-python`'s native dependency bloat didn't justify its return given that the runtime contract is already captured by `docs/api-contracts.md`, both services' live `/openapi.json`, and the integration suite that exercises the full Gateway → Account flow.

**Artifacts**
- `DESIGN.md` — design document.
- `docs/api-contracts.md` — API contract reference.
- `docs/diagrams/*.mmd` — three Mermaid diagrams (architecture, sequence, state machine).

---

## Development Agent

**What it did**
- Scaffolded both services with consistent shapes (api / core / db / schemas / services).
- Implemented the error hierarchy (`LedgerError → ValidationError, DuplicateEventError, AccountServiceUnavailableError, AccountServiceClientError`) and the global FastAPI exception handlers that return a uniform `{error: {code, message, traceId}}` envelope.
- Wrote the JSON-logging configuration (`structlog`) with a custom processor that pulls the current span's trace id onto every log line.
- Built the durable audit trail: a `audit_log` table on both services, written from `app/audit/audit.py`, mirrored as a `audit=true` JSON log line so log shippers see it too.
- Implemented the resilient `AccountClient` and the in-house async circuit breaker after discovering `pybreaker.call_async` is Tornado-bound and silently miscounts asyncio failures.
- Implemented the outbox replayer as a `lifespan`-managed background task.

**What I caught and corrected**
- An initial attempt to compute the balance using SQL `CAST(... AS NUMERIC)` was incorrect for `Decimal` safety on SQLite (which stores TEXT amounts as bytes). Switched to Python-side summation so balance math is exact.
- An incorrect retry pattern (`async for attempt in retrying` with `return` inside `with attempt:`) didn't surface results; switched to the proper "set_result on success" pattern.
- The `pybreaker.call_async` Tornado dependency — caught it during a smoke test and rewrote the breaker in-house.

**Commit hygiene**
The repo has ~10 commits, each one explaining the *why* in the body, not just the *what*. No squash. Run `git log --format="%h %s"` for the timeline.

---

## QA Agent

**What it did**
- Generated unit + integration test suites covering every requirement in the handout:
  - 17 tests on the Account Service (validation, idempotency, balance, audit).
  - 43 tests on the Gateway (validation, idempotency, out-of-order, graceful degradation, circuit breaker state transitions, retry semantics, trace propagation, outbox replay, real-HTTP path via `respx`).
- Created a test infrastructure that:
  - Isolates each test with its own ephemeral SQLite file (`tmp_path` fixture).
  - Provides a `FakeAccountClient` that subclasses the real client and only overrides `_one_call`, so tests exercise the full resiliency stack against a programmable fake.
  - Adds a `respx`-based path that exercises the real `httpx` code (status mapping, retry, health probe) without binding tests to the network.
- Generated coverage reports (line coverage **94 % gateway / 96 % account**) and committed the HTML reports under `docs/coverage/` so the reviewer can browse line-by-line.
- Wrote the **functional coverage matrix** (`docs/functional-coverage.md`) mapping each handout requirement to the specific test that proves it — this is more directly meaningful than a raw % for a reviewer.

**Verification I ran manually**
- Brought up the account service in a subprocess, hit it with curl/httpx end-to-end before writing tests, to confirm the API shape.
- Stopped the account service mid-run to confirm the gateway degrades to 503+QUEUED and that local GETs continue to work.
- Confirmed the trace id appears in logs from both services for the same request.

---

## What the AI did not do

- **Design decisions** — those were made jointly, with the AI surfacing options and trade-offs.
- **Library choices on hidden constraints** — when `pybreaker` looked superficially right but turned out to be Tornado-only async, the human caught it during a smoke test.
- **Acceptance of a "test passes therefore done" result** — coverage was reviewed line-by-line and the matrix written explicitly to map requirements to tests.

The summary: AI accelerated the long tail (scaffolding, repetitive validation cases, audit/logging wiring, coverage report generation, doc drafting) while leaving the load-bearing decisions to the human.
