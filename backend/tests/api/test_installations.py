import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings
from app.main import create_app
from app.services.tokens import hash_token

BACKEND_ROOT = Path(__file__).parents[2]


def _database_url() -> str:
    url = os.getenv("BILI_AI_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("BILI_AI_TEST_DATABASE_URL is required for API tests")
    if not urlparse(url).path.removeprefix("/").endswith("_test"):
        pytest.fail("BILI_AI_TEST_DATABASE_URL database name must end with '_test'")
    return url


def _redis_url() -> str:
    url = os.getenv("BILI_AI_TEST_REDIS_URL")
    if url is None:
        pytest.skip("BILI_AI_TEST_REDIS_URL is required for API tests")
    return url


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[str]:
    url = _database_url()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    yield url


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(migrated_database)
    try:
        yield database_engine
    finally:
        await database_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_state(engine: AsyncEngine) -> AsyncIterator[None]:
    redis = Redis.from_url(_redis_url(), decode_responses=True)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE installation_token"))
    await redis.flushdb()
    await redis.aclose()
    yield


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": _database_url(),
        "redis_url": _redis_url(),
        "allowed_extension_origins": ["chrome-extension://abcdefghijklmnop"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_registration_returns_raw_token_and_stores_only_hash(
    engine: AsyncEngine,
) -> None:
    app = create_app(_settings())
    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/installations")

    assert response.status_code == 201
    payload = response.json()
    assert len(payload["token"]) >= 43
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT token_hash, created_at FROM installation_token")
            )
        ).mappings().one()
    assert row["token_hash"] == hash_token(payload["token"])
    assert payload["token"] not in row["token_hash"]
    assert payload["created_at"] == row["created_at"].isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_invalid_and_revoked_tokens_are_rejected() -> None:
    app = create_app(_settings())
    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        invalid = await client.post(
            "/api/v1/installations/rotate",
            headers={"Authorization": "Bearer invalid"},
        )
        registered = await client.post("/api/v1/installations")
        old_token = registered.json()["token"]
        rotated = await client.post(
            "/api/v1/installations/rotate",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        rejected_old = await client.post(
            "/api/v1/installations/rotate",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        accepted_new = await client.post(
            "/api/v1/installations/rotate",
            headers={"Authorization": f"Bearer {rotated.json()['token']}"},
        )

    assert invalid.status_code == 401
    assert rotated.status_code == 200
    assert rejected_old.status_code == 401
    assert accepted_new.status_code == 200


@pytest.mark.asyncio
async def test_registration_ip_limit_prevents_database_writes(
    engine: AsyncEngine,
) -> None:
    app = create_app(
        _settings(registration_ip_burst_limit=2, registration_ip_daily_limit=10)
    )
    async with app.router.lifespan_context(app), AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.9", 1234)),
        base_url="http://test",
    ) as client:
        responses = [
            await client.post("/api/v1/installations") for _ in range(3)
        ]

    assert [response.status_code for response in responses] == [201, 201, 429]
    async with engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM installation_token"))
    assert count == 2


@pytest.mark.asyncio
async def test_authentication_bounds_last_used_writes_and_rejects_idle_tokens(
    engine: AsyncEngine,
) -> None:
    app = create_app(_settings(token_last_used_write_minutes=60))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        registered = await client.post("/api/v1/installations")
        token = registered.json()["token"]
        first = await app.state.token_service.authenticate(token)
        assert first is not None
        async with engine.connect() as connection:
            first_seen = await connection.scalar(
                text(
                    "SELECT last_used_at FROM installation_token "
                    "WHERE token_hash = :token_hash"
                ),
                {"token_hash": hash_token(token)},
            )
        second = await app.state.token_service.authenticate(token)
        assert second is not None
        async with engine.connect() as connection:
            second_seen = await connection.scalar(
                text(
                    "SELECT last_used_at FROM installation_token "
                    "WHERE token_hash = :token_hash"
                ),
                {"token_hash": hash_token(token)},
            )
        assert second_seen == first_seen

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE installation_token SET created_at = :idle, last_used_at = NULL "
                    "WHERE token_hash = :token_hash"
                ),
                {
                    "idle": datetime.now(UTC) - timedelta(days=91),
                    "token_hash": hash_token(token),
                },
            )
        assert await app.state.token_service.authenticate(token) is None
