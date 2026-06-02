import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OTEL_ENABLED", "false")

from app.core.config import get_settings  # noqa: E402
from app.db import session as session_mod  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """Each test gets its own SQLite file so suites don't see each other's data."""
    db_file = tmp_path / "account.db"
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
    yield


@pytest_asyncio.fixture
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
