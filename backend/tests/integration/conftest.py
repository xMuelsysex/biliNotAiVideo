import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

BACKEND_ROOT = Path(__file__).parents[2]


def _database_url() -> str:
    url = os.getenv("BILI_AI_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("BILI_AI_TEST_DATABASE_URL is required")
    if not urlparse(url).path.removeprefix("/").endswith("_test"):
        pytest.fail("test database name must end with _test")
    return url


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
                "video_metadata, analysis_attempt, analysis_target CASCADE"
            )
        )
    try:
        yield database_engine
    finally:
        await database_engine.dispose()
