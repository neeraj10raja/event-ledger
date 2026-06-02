#!/usr/bin/env bash
# Smoke test: exercises the full Event Ledger end-to-end against the
# running docker-compose stack. Requires `curl` and `jq`.
set -euo pipefail

GATEWAY=${GATEWAY:-http://localhost:8000}
ACCOUNT=${ACCOUNT:-http://localhost:8001}

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
fail() { printf "\033[1;31mFAIL: %s\033[0m\n" "$*" >&2; exit 1; }

say "Health (gateway)"
curl -fsS "$GATEWAY/health" | jq .

say "Health (account)"
curl -fsS "$ACCOUNT/health" | jq .

ACCT="acct-smoke-$(date +%s)"
EID1="evt-$(uuidgen | tr A-Z a-z)"
EID2="evt-$(uuidgen | tr A-Z a-z)"

say "POST CREDIT 150 (expect 201)"
curl -fsS -X POST "$GATEWAY/events" -H 'content-type: application/json' \
  -d "{\"eventId\":\"$EID1\",\"accountId\":\"$ACCT\",\"type\":\"CREDIT\",\"amount\":\"150.00\",\"currency\":\"USD\",\"eventTimestamp\":\"2026-05-15T14:02:11Z\"}" | jq .

say "POST same eventId again (expect 200, balance unchanged)"
status=$(curl -s -o /tmp/dup.json -w "%{http_code}" -X POST "$GATEWAY/events" -H 'content-type: application/json' \
  -d "{\"eventId\":\"$EID1\",\"accountId\":\"$ACCT\",\"type\":\"CREDIT\",\"amount\":\"150.00\",\"currency\":\"USD\",\"eventTimestamp\":\"2026-05-15T14:02:11Z\"}")
cat /tmp/dup.json | jq .
[[ "$status" == "200" ]] || fail "expected 200 on duplicate, got $status"

say "POST DEBIT 40 with earlier timestamp (out-of-order)"
curl -fsS -X POST "$GATEWAY/events" -H 'content-type: application/json' \
  -d "{\"eventId\":\"$EID2\",\"accountId\":\"$ACCT\",\"type\":\"DEBIT\",\"amount\":\"40.00\",\"currency\":\"USD\",\"eventTimestamp\":\"2026-05-14T10:00:00Z\"}" | jq .

say "GET events list (should be chronological)"
curl -fsS "$GATEWAY/events?account=$ACCT" | jq '.items | map({eventId, eventTimestamp})'

say "GET balance (expect 110.00)"
curl -fsS "$ACCOUNT/accounts/$ACCT/balance" | jq .

say "POST invalid payload (negative amount, expect 400)"
status=$(curl -s -o /tmp/err.json -w "%{http_code}" -X POST "$GATEWAY/events" -H 'content-type: application/json' \
  -d "{\"eventId\":\"bad\",\"accountId\":\"$ACCT\",\"type\":\"CREDIT\",\"amount\":\"-1\",\"currency\":\"USD\",\"eventTimestamp\":\"2026-05-15T14:02:11Z\"}")
cat /tmp/err.json | jq .
[[ "$status" == "400" ]] || fail "expected 400 on invalid payload, got $status"

say "Prometheus metrics sample"
curl -fsS "$GATEWAY/metrics" | grep -E '^(events_received_total|circuit_breaker_state|outbox_depth)' || true

printf "\n\033[1;32mSmoke test passed.\033[0m\n"
