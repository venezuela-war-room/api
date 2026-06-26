import asyncio
import hashlib
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import ApiKey

TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/terremoto_test"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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
