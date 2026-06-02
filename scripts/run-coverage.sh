#!/usr/bin/env bash
# Run unit + integration suites for both services with coverage, then
# copy the HTML reports under docs/coverage/{gateway,account}/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
PYTEST="${PYTEST:-$ROOT/.venv/bin/pytest}"

run_one() {
  local name="$1"
  local svc_dir="$ROOT/services/$name"
  local out_dir="$ROOT/docs/coverage/$name"
  printf "\n\033[1;34m==> Coverage: %s\033[0m\n" "$name"
  rm -rf "$out_dir" "$svc_dir/htmlcov" "$svc_dir/.coverage" "$svc_dir/coverage.xml"
  (
    cd "$svc_dir"
    "$PYTEST" \
      --cov=app \
      --cov-report=term-missing \
      --cov-report=html \
      --cov-report=xml
  )
  mkdir -p "$out_dir"
  cp -r "$svc_dir/htmlcov/." "$out_dir/"
  cp "$svc_dir/coverage.xml" "$out_dir/coverage.xml"
}

run_one gateway
run_one account

printf "\n\033[1;32mCoverage reports written to %s\033[0m\n" "$ROOT/docs/coverage/"
