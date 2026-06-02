# API Contracts

Authoritative request/response shapes for both services. The OpenAPI spec is also auto-served at `/docs` (Swagger) and `/openapi.json` on each service.

## Event Gateway (`:8000`)

### `POST /events`

Request body:
```json
{
  "eventId": "evt-001",
  "accountId": "acct-123",
  "type": "CREDIT",
  "amount": "150.00",
  "currency": "USD",
  "eventTimestamp": "2026-05-15T14:02:11Z",
  "metadata": {"source": "mainframe-batch", "batchId": "B-9042"}
}
```

| Status | Meaning | Body |
|---|---|---|
| `201` | New event accepted and applied | `EventOut` |
| `200` | Idempotent replay of a previously applied event | `EventOut` (status=APPLIED) |
| `202` | Idempotent replay of an event still queued | `EventOut` (status=QUEUED) |
| `400` | Validation error | `ErrorOut` |
| `429` | Rate limited | `ErrorOut` |
| `503` | Account Service unavailable; event queued for replay | `EventOut` (status=QUEUED) |

`EventOut` shape:
```json
{
  "eventId": "evt-001",
  "accountId": "acct-123",
  "type": "CREDIT",
  "amount": "150.00",
  "currency": "USD",
  "eventTimestamp": "2026-05-15T14:02:11Z",
  "metadata": {"source": "mainframe-batch"},
  "status": "APPLIED",
  "receivedAt": "2026-06-02T20:00:00.123Z",
  "traceId": "4b…"
}
```

`ErrorOut` shape:
```json
{"error": {"code": "VALIDATION_ERROR", "message": "amount must be > 0", "traceId": "4b…"}}
```

### `GET /events/{id}`
- `200` → `EventOut`
- `404` → `ErrorOut` (`EVENT_NOT_FOUND`)

### `GET /events?account={accountId}&limit={n}&offset={m}`
- `200` → `{items: [EventOut], total: int}` ordered by `eventTimestamp` ASC

### `GET /health`
```json
{
  "status": "ok",
  "service": "event-gateway",
  "version": "0.1.0",
  "checks": {"db": "ok", "account_service": "ok"},
  "circuitBreaker": "closed"
}
```

## Account Service (`:8001`)

### `POST /accounts/{accountId}/transactions`

Request body:
```json
{
  "eventId": "evt-001",
  "type": "CREDIT",
  "amount": "150.00",
  "currency": "USD",
  "eventTimestamp": "2026-05-15T14:02:11Z"
}
```

| Status | Meaning |
|---|---|
| `201` | New transaction applied |
| `200` | Duplicate `eventId` — idempotent hit |
| `400` | Validation error |

Response (success):
```json
{
  "eventId": "evt-001",
  "accountId": "acct-123",
  "balance": "150.00",
  "currency": "USD",
  "appliedAt": "2026-06-02T20:00:00.123Z"
}
```

### `GET /accounts/{accountId}/balance`
```json
{"accountId": "acct-123", "balance": "150.00", "currency": "USD"}
```

### `GET /accounts/{accountId}`
```json
{
  "accountId": "acct-123",
  "balance": "150.00",
  "currency": "USD",
  "recentTransactions": [
    {"eventId": "evt-001", "type": "CREDIT", "amount": "150.00", "eventTimestamp": "2026-05-15T14:02:11Z"}
  ]
}
```

## Trace Propagation

All inter-service calls carry the W3C `traceparent` header. Both services emit `trace_id` on every log line so a single trace can be reconstructed from logs alone.
