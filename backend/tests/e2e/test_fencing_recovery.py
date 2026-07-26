import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.repository import AnalysisRepository, AnalysisResultWrite
from app.domain.types import EvidenceItem, LabelKey, TargetKey
from app.services.outbox import OutboxDispatcher, RedisStreamPublisher
from app.services.reconciliation import AttemptReconciler

BACKEND_ROOT = Path(__file__).parents[2]


def _database_url() -> str:
    url = os.getenv("BILI_AI_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("BILI_AI_TEST_DATABASE_URL is required")
    if not urlparse(url).path.removeprefix("/").endswith("_test"):
        pytest.fail("test database name must end with _test")
    return url


def _redis_url() -> str:
    url = os.getenv("BILI_AI_TEST_REDIS_URL")
    if url is None:
        pytest.skip("BILI_AI_TEST_REDIS_URL is required")
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
    redis = Redis.from_url(_redis_url())
    await redis.flushdb()
    await redis.aclose()
    try:
        yield database_engine
    finally:
        await database_engine.dispose()


@pytest_asyncio.fixture
async def repository(engine: AsyncEngine) -> AnalysisRepository:
    return AnalysisRepository(async_sessionmaker(engine, expire_on_commit=False))


def _result(version: str, score: int, now: datetime) -> AnalysisResultWrite:
    return AnalysisResultWrite(
        score=score,
        label=LabelKey.MEDIUM,
        confidence=0.8,
        evidence=(EvidenceItem(description=f"evidence-{version}"),),
        analysis_version=version,
        analyzed_at=now,
        analysis_expires_at=now + timedelta(days=14),
    )


@pytest.mark.asyncio
async def test_redis_flush_redispatches_via_postgres_outbox(
    repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    now = datetime.now(UTC)
    decision = await repository.create_or_reuse_attempt(
        TargetKey("BV1flush1111", 11), "v1", now
    )
    redis = Redis.from_url(_redis_url(), decode_responses=True)
    publisher = RedisStreamPublisher(redis, "e2e-flush")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    dispatcher = OutboxDispatcher(session_factory, publisher)
    assert await dispatcher.dispatch_batch(limit=10) == 1
    before = await redis.xlen("e2e-flush")
    assert before >= 1
    await redis.flushdb()
    assert await redis.xlen("e2e-flush") == 0
    reconciler = AttemptReconciler(session_factory)
    await reconciler.reconcile(
        now=now + timedelta(minutes=10),
        dispatch_timeout=timedelta(seconds=1),
    )
    assert await dispatcher.dispatch_batch(limit=10) >= 1
    assert await redis.xlen("e2e-flush") >= 1
    async with engine.connect() as connection:
        epoch = await connection.scalar(
            text(
                "SELECT dispatch_epoch FROM analysis_attempt "
                "WHERE attempt_id = :attempt_id"
            ),
            {"attempt_id": decision.attempt.attempt_id},
        )
    assert int(epoch or 0) >= 1
    await redis.aclose()


@pytest.mark.asyncio
async def test_stale_worker_cannot_overwrite_after_reclaim(
    repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    now = datetime.now(UTC)
    target = TargetKey("BV1lease2222", 22)
    decision = await repository.create_or_reuse_attempt(target, "v1", now)
    claim = await repository.claim_attempt(
        decision.attempt.attempt_id,
        decision.attempt.generation,
        decision.attempt.dispatch_epoch,
        1,
    )
    assert claim is not None
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE analysis_attempt SET lease_expires_at = :expired "
                "WHERE attempt_id = :attempt_id"
            ),
            {
                "expired": now - timedelta(seconds=5),
                "attempt_id": decision.attempt.attempt_id,
            },
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    await AttemptReconciler(session_factory).reconcile(
        now=now + timedelta(seconds=10),
        dispatch_timeout=timedelta(seconds=1),
    )
    stale_complete = await repository.complete_attempt(claim, _result("v1", 12, now))
    assert stale_complete is False
    refreshed = await repository.create_or_reuse_attempt(target, "v1", now)
    live = await repository.claim_attempt(
        refreshed.attempt.attempt_id,
        refreshed.attempt.generation,
        refreshed.attempt.dispatch_epoch,
        60,
    )
    assert live is not None
    assert await repository.complete_attempt(live, _result("v1", 77, now))
    async with engine.connect() as connection:
        score = await connection.scalar(
            text("SELECT score FROM analysis_result WHERE bvid = :bvid AND cid = :cid"),
            {"bvid": target.bvid, "cid": target.cid},
        )
    assert score == 77
