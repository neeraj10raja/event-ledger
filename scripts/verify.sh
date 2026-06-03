#!/usr/bin/env bash
# verify.sh — the critic in the actor-critic loop.
#
# Runs a fixed catalogue of mechanical assertions against the repo:
# every claim in the README and design docs is checked against what's
# actually in the code.  Each assertion is a single function that
# echoes one line of evidence and returns 0 (pass) or 1 (fail).
#
# Writes docs/verification-report.md and exits non-zero on any fail.
#
# Designed to run on both macOS (developer machines) and Ubuntu (CI)
# with no dependencies beyond the standard Unix toolchain and python3.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REPORT="docs/verification-report.md"
GENERATED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"

# ── Assertion plumbing ──────────────────────────────────────────────
results=()          # "PASS|FAIL|name|evidence"
total=0
failed=0

record() {
  # record <result PASS|FAIL> <name> <evidence>
  local result="$1" name="$2" evidence="$3"
  results+=("${result}|${name}|${evidence}")
  total=$((total + 1))
  if [ "$result" = "FAIL" ]; then
    failed=$((failed + 1))
    printf "  ❌ %s\n     %s\n" "$name" "$evidence" >&2
  else
    printf "  ✅ %s\n" "$name"
  fi
}

# ── Assertions ──────────────────────────────────────────────────────

assert_test_counts_match_readme() {
  local name="README test counts match pytest collection"
  local gw acct readme_gw readme_acct readme_total
  # `pytest --collect-only` (no -q) prints "N tests collected" at the end.
  gw=$(cd services/gateway && python3 -m pytest --collect-only 2>/dev/null \
        | grep -oE "[0-9]+ tests collected" | head -1 | awk '{print $1}')
  acct=$(cd services/account && python3 -m pytest --collect-only 2>/dev/null \
        | grep -oE "[0-9]+ tests collected" | head -1 | awk '{print $1}')

  if [ -z "$gw" ] || [ -z "$acct" ]; then
    record FAIL "$name" "could not collect tests (gateway=$gw account=$acct)"
    return
  fi

  readme_gw=$(grep -E "^\| Gateway \| [0-9]+ \|" README.md | head -1 | awk '{print $4}')
  readme_acct=$(grep -E "^\| Account \| [0-9]+ \|" README.md | head -1 | awk '{print $4}')
  readme_total=$(grep -E "^\| \*\*Total\*\* \| \*\*[0-9]+\*\*" README.md | head -1 \
                  | sed -E 's/.*\*\*([0-9]+)\*\*.*/\1/')

  if [ "$readme_gw" = "$gw" ] && [ "$readme_acct" = "$acct" ] \
     && [ "$readme_total" = "$((gw + acct))" ]; then
    record PASS "$name" "gateway=$gw account=$acct total=$((gw + acct))"
  else
    record FAIL "$name" \
      "actual gw=$gw acct=$acct; readme gw=$readme_gw acct=$readme_acct total=$readme_total"
  fi
}

assert_no_forbidden_pybreaker_imports() {
  local name="No live pybreaker imports (we shipped an in-house breaker)"
  if grep -rE "^(import|from) +pybreaker" services/ >/dev/null 2>&1; then
    local hits
    hits=$(grep -rEn "^(import|from) +pybreaker" services/ | head -1)
    record FAIL "$name" "found: $hits"
  else
    record PASS "$name" "no imports under services/"
  fi
}

assert_no_pybreaker_in_requirements() {
  local name="No pybreaker pinned in any requirements file"
  if grep -lE "^pybreaker" services/*/requirements*.txt >/dev/null 2>&1; then
    record FAIL "$name" "pybreaker found in requirements"
  else
    record PASS "$name" "requirements clean"
  fi
}

assert_no_pact_test_files() {
  local name="ai-workflow.md descopes Pact, so no pact_*.py exists"
  local hits
  hits=$(find services -type f \( -name "test_pact*.py" -o -name "*pact_consumer*.py" -o -name "*pact_provider*.py" \) 2>/dev/null)
  if [ -n "$hits" ]; then
    record FAIL "$name" "stray pact test file: $(echo "$hits" | head -1)"
  else
    record PASS "$name" "no pact test files; matches docs/ai-workflow.md"
  fi
}

assert_documented_endpoints_implemented() {
  local name="Every endpoint in README is implemented in app/api/"
  # Strategy: for each documented (GET|POST) /path, normalise the path
  # template (drop everything inside `{...}` for matching), then assert
  # a router decorator with the same method and a matching path exists
  # under services/*/app/api/.
  local declared
  declared=$(grep -hoE '\b(GET|POST) /[a-zA-Z/{}_-]+' README.md docs/api-contracts.md \
             | sort -u)
  if [ -z "$declared" ]; then
    record FAIL "$name" "could not extract any endpoint declarations from docs"
    return
  fi

  # Collect all defined routes once.  FastAPI's router decorators can
  # span multiple lines (`@router.post(\n  "/events",\n  ...)`), so we
  # read the whole file rather than grep'ing line by line.  Format:
  # METHOD PATH-STUB, with {...} stripped so any param name matches.
  local defined
  defined=$(python3 -c '
import re, glob
seen = set()
for path in glob.glob("services/*/app/api/*.py"):
    with open(path) as f:
        text = f.read()
    for m in re.finditer(r"@router\.(get|post)\(\s*\"([^\"]+)\"", text):
        method = m.group(1).upper()
        endpoint = re.sub(r"\{[^}]+\}", "", m.group(2))
        seen.add(f"{method} {endpoint}")
for line in sorted(seen):
    print(line)
')

  local missing=""
  while read -r decl; do
    local method path normalised
    method="${decl%% *}"
    path="${decl#* }"
    normalised=$(echo "$path" | sed -E 's/\{[^}]+\}//g')
    if ! grep -Fqx "$method $normalised" <<< "$defined"; then
      missing="${missing}${decl}; "
    fi
  done <<< "$declared"

  if [ -z "$missing" ]; then
    record PASS "$name" "$(echo "$declared" | wc -l | tr -d ' ') endpoints, all resolved"
  else
    record FAIL "$name" "undocumented or missing: ${missing%; }"
  fi
}

assert_audit_actions_implemented() {
  local name="Every audit action documented in DESIGN.md exists in audit-emitting code"
  # Actions appear as upper-snake tokens in a · separated list in DESIGN.md and README.
  local actions="RECEIVED DEDUPED APPLIED FAILED QUEUED REPLAYED"
  local missing=""
  for action in $actions; do
    if ! grep -REq "action=\"$action\"" services/*/app/ 2>/dev/null; then
      missing="$missing $action"
    fi
  done
  if [ -z "$missing" ]; then
    record PASS "$name" "$(echo "$actions" | wc -w | tr -d ' ') actions present"
  else
    record FAIL "$name" "missing in code:$missing"
  fi
}

assert_diagrams_exist() {
  local name="Every Mermaid diagram referenced in DESIGN.md exists on disk"
  # DESIGN.md sits at repo root, so references use the relative path
  # `diagrams/architecture.mmd` (which resolves to docs/diagrams/...
  # when the doc is rendered inside docs/).  Accept either form.
  local refs missing=""
  refs=$(grep -oE "(docs/)?diagrams/[a-z-]+\.mmd" DESIGN.md | sort -u)
  if [ -z "$refs" ]; then
    record FAIL "$name" "no diagram references found in DESIGN.md"
    return
  fi
  while read -r f; do
    # Normalise: if reference is "diagrams/x.mmd", look under docs/.
    local resolved="$f"
    case "$f" in
      docs/*) ;;
      *) resolved="docs/$f" ;;
    esac
    [ -f "$resolved" ] || missing="$missing $f"
  done <<< "$refs"
  if [ -z "$missing" ]; then
    record PASS "$name" "$(echo "$refs" | wc -l | tr -d ' ') referenced, all present"
  else
    record FAIL "$name" "missing:$missing"
  fi
}

assert_suresh_deliverables_present() {
  local name="All deliverables in Suresh's guidance are present"
  local missing=""
  [ -f DESIGN.md ] || missing="$missing DESIGN.md"
  [ -d docs/diagrams ] || missing="$missing docs/diagrams/"
  [ -f docs/functional-coverage.md ] || missing="$missing docs/functional-coverage.md"
  [ -d docs/coverage/gateway ] || missing="$missing docs/coverage/gateway/"
  [ -d docs/coverage/account ] || missing="$missing docs/coverage/account/"
  grep -q "class LedgerError" services/gateway/app/core/errors.py 2>/dev/null \
    || missing="$missing LedgerError"
  grep -q "structlog.configure" services/gateway/app/core/logging.py 2>/dev/null \
    || missing="$missing structlog-config"
  grep -q "audit_log" services/gateway/app/db/models.py 2>/dev/null \
    || missing="$missing audit_log-table"
  local agent_count
  agent_count=$(ls .claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ')
  [ "$agent_count" -ge 3 ] || missing="$missing agents(<3)"
  if [ -z "$missing" ]; then
    record PASS "$name" "all deliverables present; $agent_count agents"
  else
    record FAIL "$name" "missing:$missing"
  fi
}

assert_no_leaked_todos() {
  local name="No TODO/FIXME/XXX comments in production code"
  local hits
  hits=$(grep -rEn "^[^/]*(TODO|FIXME|XXX)\b" services/*/app/ 2>/dev/null \
          | grep -v "verify.sh" | head -3)
  if [ -n "$hits" ]; then
    record FAIL "$name" "found: $(echo "$hits" | head -1)"
  else
    record PASS "$name" "no leaked TODOs under services/*/app/"
  fi
}

assert_referenced_test_files_exist() {
  local name="Every test path cited in functional-coverage.md exists"
  # Backticked paths like `gateway/tests/integration/test_post_events_flow.py`
  # may be followed by `::test_name` — strip the test-id, keep just the file.
  local refs missing=""
  refs=$(grep -oE '`(gateway|account)/tests/[a-zA-Z0-9_/.-]+\.py' docs/functional-coverage.md \
          | tr -d '`' | sort -u)
  if [ -z "$refs" ]; then
    record FAIL "$name" "no test paths found in functional-coverage.md"
    return
  fi
  while read -r p; do
    [ -f "services/$p" ] || missing="$missing services/$p"
  done <<< "$refs"
  if [ -z "$missing" ]; then
    record PASS "$name" "$(echo "$refs" | wc -l | tr -d ' ') paths cited, all present"
  else
    record FAIL "$name" "missing:$missing"
  fi
}

# ── Run all assertions ──────────────────────────────────────────────

printf "Verifying Event Ledger repo at %s (commit %s)\n\n" "$GENERATED_AT" "$COMMIT"

assert_test_counts_match_readme
assert_no_forbidden_pybreaker_imports
assert_no_pybreaker_in_requirements
assert_no_pact_test_files
assert_documented_endpoints_implemented
assert_audit_actions_implemented
assert_diagrams_exist
assert_suresh_deliverables_present
assert_no_leaked_todos
assert_referenced_test_files_exist

printf "\n%d / %d passed.\n" "$((total - failed))" "$total"

# ── Write the report ────────────────────────────────────────────────

{
  echo "# Verification Report"
  echo ""
  echo "_Generated: ${GENERATED_AT}_  ·  _Commit: ${COMMIT}_"
  echo ""
  if [ "$failed" -eq 0 ]; then
    echo "**Summary:** ✅ ${total} / ${total} passed."
  else
    echo "**Summary:** ❌ $((total - failed)) / ${total} passed — ${failed} failing."
  fi
  echo ""
  echo "| # | Assertion | Result | Evidence |"
  echo "|---|---|---|---|"
  i=0
  for row in "${results[@]}"; do
    i=$((i + 1))
    IFS='|' read -r result name evidence <<< "$row"
    icon="✅"
    [ "$result" = "FAIL" ] && icon="❌"
    printf "| %d | %s | %s | %s |\n" "$i" "$name" "$icon" "$evidence"
  done
  echo ""
  echo "_Generated by \`scripts/verify.sh\`; see [\`.claude/agents/verifier-agent.md\`](../.claude/agents/verifier-agent.md) for the actor-critic loop this is part of._"
} > "$REPORT"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
