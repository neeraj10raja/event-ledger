import os
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite+aiosqlite:///"):
        path = url.replace("sqlite+aiosqlite:///", "", 1)
        if path and not path.startswith(":memory:"):
            Path(os.path.dirname(path) or ".").mkdir(parents=True, exist_ok=True)


def make_engine(url: str | None = None):
    settings = get_settings()
    url = url or settings.database_url
    _ensure_sqlite_dir(url)
    return create_async_engine(url, future=True, echo=False)


engine = make_engine()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
