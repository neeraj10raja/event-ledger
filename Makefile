.DEFAULT_GOAL := help
.PHONY: help install install-dev test coverage up down logs smoke clean rebuild urls fmt

PY        := .venv/bin/python
PIP       := .venv/bin/pip
PYTEST    := .venv/bin/pytest

help:  ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv:  ## Create a local virtualenv (.venv).
	@test -d .venv || python3 -m venv .venv
	@$(PIP) install --quiet --upgrade pip

install: venv  ## Install runtime dependencies for both services.
	$(PIP) install -r services/gateway/requirements.txt -r services/account/requirements.txt

install-dev: venv  ## Install runtime + test dependencies.
	$(PIP) install -r services/gateway/requirements-dev.txt -r services/account/requirements-dev.txt

test:  ## Run the test suites for both services.
	cd services/gateway && ../../$(PYTEST)
	cd services/account && ../../$(PYTEST)

coverage:  ## Run both suites with coverage; HTML lands in docs/coverage/.
	./scripts/run-coverage.sh

up:  ## Bring up the docker-compose stack (gateway, account, jaeger, prometheus, otel).
	docker compose up --build -d
	@$(MAKE) urls

down:  ## Stop the docker-compose stack and clean up containers.
	docker compose down

logs:  ## Tail logs from both services.
	docker compose logs -f gateway account

smoke:  ## Run the end-to-end smoke test against the running stack.
	./scripts/smoke.sh

urls:  ## Print the local service URLs.
	@printf "\n  Gateway   \033[36m%s\033[0m  (docs at /docs)\n" "http://localhost:8000"
	@printf "  Account   \033[36m%s\033[0m  (docs at /docs)\n" "http://localhost:8001"
	@printf "  Jaeger    \033[36m%s\033[0m\n" "http://localhost:16686"
	@printf "  Prom      \033[36m%s\033[0m\n\n" "http://localhost:9090"

rebuild: down  ## Tear everything down and rebuild from scratch.
	docker compose build --no-cache
	$(MAKE) up

clean:  ## Remove caches, coverage artefacts, and the local venv.
	rm -rf .venv .pytest_cache
	rm -rf services/*/.pytest_cache services/*/htmlcov services/*/.coverage services/*/coverage.xml
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
