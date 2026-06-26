import hashlib
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import ApiKey

load_dotenv(Path(__file__).parent.parent / ".env")

_base_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto")
TEST_DB_URL = _base_url.rsplit("/", 1)[0] + "/terremoto_test"


@pytest_asyncio.fixture(scope="session")
async def engine():
    _engine = create_async_engine(TEST_DB_URL, echo=False)
    async with _engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "unaccent"'))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    await _engine.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    TestSession = async_sessionmaker(engine, expire_on_commit=False)
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(engine) -> AsyncGenerator[AsyncClient, None]:
    TestSession = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_key(db: AsyncSession) -> tuple[str, ApiKey]:
    raw = "tvwr_test_" + uuid.uuid4().hex
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    api_key = ApiKey(key_prefix=raw[:12], key_hash=key_hash, team_name="test-team", is_active=True)
    db.add(api_key)
    await db.commit()
    return raw, api_key
