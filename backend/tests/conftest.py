import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://messenger:messenger@localhost:5432/messenger_test"
)
# Must be set before the app is imported: engine and settings are created at import time.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET"] = "test-jwt-secret-that-is-at-least-32-bytes-long"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import make_url, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from tests.helpers import ChatUser, bearer, register  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
async def _migrated_database() -> None:
    """Recreates the test database and applies the real migrations to it."""
    url = make_url(TEST_DATABASE_URL)
    admin_engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    await admin_engine.dispose()

    # Alembic's env.py calls asyncio.run(), so it needs its own thread.
    await asyncio.to_thread(command.upgrade, Config(BACKEND_DIR / "alembic.ini"), "head")


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def users(client: AsyncClient) -> dict[str, ChatUser]:
    result = {}
    for name in ("alice", "bob", "carol", "dave"):
        body = await register(client, name)
        result[name] = ChatUser(body["user"]["id"], name, bearer(body["access_token"]))
    return result
