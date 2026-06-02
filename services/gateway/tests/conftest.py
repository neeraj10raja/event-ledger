import os
from typing import Any, Iterable
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("OUTBOX_ENABLED", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("RETRY_MIN_WAIT_SECONDS", "0.001")
os.environ.setdefault("RETRY_MAX_WAIT_SECONDS", "0.005")

from app.core.config import get_settings  # noqa: E402
from app.db import session as session_mod  # noqa: E402
from app.main import create_app  # noqa: E402
from app.resilience.circuit_breaker import reset_breaker  # noqa: E402
from app.services.account_client import AccountClient  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    db_file = tmp_path / "gateway.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    new_engine = session_mod.make_engine(url)
    monkeypatch.setattr(session_mod, "engine", new_engine)
    monkeypatch.setattr(
        session_mod,
        "SessionLocal",
        session_mod.async_sessionmaker(new_engine, class_=session_mod.AsyncSession, expire_on_commit=False),
    )
    reset_breaker()
    yield


class FakeAccountClient(AccountClient):
    """Replaces the real httpx client with a programmable fake.

    Two control modes:
    - `set_outcomes([...])` drives successive calls; falls back to success when exhausted.
    - `fail_with(exc)` makes every call raise `exc` until cleared via `fail_with(None)`.
    """

    def __init__(self, outcomes: Iterable[Any] | None = None):
        super().__init__(base_url="http://fake")
        self.calls: list[dict[str, Any]] = []
        self._outcomes = list(outcomes) if outcomes else []
        self._idx = 0
        self._persistent_failure: Exception | None = None
        self.healthy = True

    def set_outcomes(self, outcomes: Iterable[Any]) -> None:
        self._outcomes = list(outcomes)
        self._idx = 0

    def fail_with(self, exc: Exception | None) -> None:
        self._persistent_failure = exc

    async def _one_call(self, account_id, event_id, type_, amount, currency, event_timestamp):
        self.calls.append(
            {"account_id": account_id, "event_id": event_id, "type": type_, "amount": str(amount)}
        )
        if self._persistent_failure is not None:
            raise self._persistent_failure
        if self._idx < len(self._outcomes):
            outcome = self._outcomes[self._idx]
            self._idx += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return {"eventId": event_id, "accountId": account_id, "balance": str(amount)}

    async def health(self) -> bool:
        return self.healthy

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def fake_account():
    return FakeAccountClient()


@pytest_asyncio.fixture
async def client(fake_account):
    app = create_app()
    async with app.router.lifespan_context(app):
        # Replace the real client created by lifespan with the fake.
        app.state.account_client = fake_account
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
