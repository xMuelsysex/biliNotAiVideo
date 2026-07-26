from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.api.test_analyses import _database_url, _redis_url

BACKEND_ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = _database_url()
    command.upgrade(config, "head")
    yield


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(_database_url())
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE analysis_outbox, analysis_result, video_declaration, "
                "video_metadata, analysis_attempt, analysis_target, "
                "installation_token CASCADE"
            )
        )
    redis = Redis.from_url(_redis_url())
    await redis.flushdb()
    await redis.aclose()
    try:
        yield database_engine
    finally:
        await database_engine.dispose()
