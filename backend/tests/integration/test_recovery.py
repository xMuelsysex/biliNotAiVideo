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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.repository import AnalysisRepository, AnalysisResultWrite
from app.domain.types import EvidenceItem, LabelKey, TargetKey
from app.services.outbox import DispatchMessage, OutboxDispatcher, RedisStreamPublisher
from app.services.reconciliation import AttemptReconciler

BACKEND_ROOT = Path(__file__).parents[2]


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages: list[DispatchMessage] = []

    async def publish(self, message: DispatchMessage) -> None:
        self.messages.append(message)


class FailingPublisher:
    async def publish(self, message: DispatchMessage) -> None:
        raise RuntimeError(f"publish failed for {message.idempotency_key}")


def _test_database_url() -> str:
    database_url = os.getenv("BILI_AI_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("BILI_AI_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    if not urlparse(database_url).path.removeprefix("/").endswith("_test"):
        pytest.fail("BILI_AI_TEST_DATABASE_URL database name must end with '_test'")
    return database_url


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[str]:
    database_url = _test_database_url()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield database_url


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(migrated_database)
    try:
        yield database_engine
    finally:
        await database_engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_database(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE analysis_outbox, analysis_result, video_declaration, "
                "analysis_attempt, analysis_target CASCADE"
            )
        )
    yield


@pytest_asyncio.fixture
async def repository(session_factory: async_sessionmaker) -> AnalysisRepository:
    return AnalysisRepository(session_factory)


@pytest.mark.asyncio
async def test_dispatcher_publishes_undelivered_event_once_per_row(
    repository: AnalysisRepository,
    session_factory: async_sessionmaker,
    engine: AsyncEngine,
) -> None:
    decision = await repository.create_or_reuse_attempt(
        TargetKey("BV1dispatch", 101), "v1", datetime.now(UTC)
    )
    publisher = RecordingPublisher()

    assert await OutboxDispatcher(session_factory, publisher).dispatch_batch(limit=10) == 1
    assert await OutboxDispatcher(session_factory, publisher).dispatch_batch(limit=10) == 0
    assert publisher.messages == [
        DispatchMessage(
            attempt_id=decision.attempt.attempt_id,
            generation=decision.attempt.generation,
            dispatch_epoch=0,
        )
    ]
    async with engine.connect() as connection:
        delivered = await connection.scalar(
            text(
                "SELECT delivered_at IS NOT NULL FROM analysis_outbox "
                "WHERE attempt_id = :attempt_id"
            ),
            {"attempt_id": decision.attempt.attempt_id},
        )
    assert delivered is True


@pytest.mark.asyncio
async def test_publish_failure_keeps_outbox_undelivered(
    repository: AnalysisRepository,
    session_factory: async_sessionmaker,
    engine: AsyncEngine,
) -> None:
    decision = await repository.create_or_reuse_attempt(
        TargetKey("BV1publishfail", 150), "v1", datetime.now(UTC)
    )
    dispatcher = OutboxDispatcher(session_factory, FailingPublisher())

    with pytest.raises(RuntimeError, match="publish failed"):
        await dispatcher.dispatch_batch(limit=10)

    async with engine.connect() as connection:
        delivered_at = await connection.scalar(
            text(
                "SELECT delivered_at FROM analysis_outbox "
                "WHERE attempt_id = :attempt_id"
            ),
            {"attempt_id": decision.attempt.attempt_id},
        )
    assert delivered_at is None


@pytest.mark.asyncio
async def test_delivered_message_is_recreated_after_dispatch_timeout(
    repository: AnalysisRepository,
    session_factory: async_sessionmaker,
) -> None:
    now = datetime.now(UTC)
    decision = await repository.create_or_reuse_attempt(
        TargetKey("BV1flush", 202), "v1", now
    )
    first_publisher = RecordingPublisher()
    assert await OutboxDispatcher(session_factory, first_publisher).dispatch_batch(limit=10) == 1

    recovered = await AttemptReconciler(session_factory).reconcile(
        now=now + timedelta(minutes=10),
        dispatch_timeout=timedelta(minutes=5),
    )
    assert recovered.redispatched == 1
    assert recovered.reclaimed == 0

    restarted_publisher = RecordingPublisher()
    restarted_dispatcher = OutboxDispatcher(session_factory, restarted_publisher)
    assert await restarted_dispatcher.dispatch_batch(limit=10) == 1
    assert restarted_publisher.messages == [
        DispatchMessage(
            attempt_id=decision.attempt.attempt_id,
            generation=decision.attempt.generation,
            dispatch_epoch=1,
        )
    ]


@pytest.mark.asyncio
async def test_redis_flush_is_recovered_with_a_new_dispatch_epoch(
    repository: AnalysisRepository,
    session_factory: async_sessionmaker,
) -> None:
    redis_url = os.getenv("BILI_AI_TEST_REDIS_URL")
    if redis_url is None:
        pytest.skip("BILI_AI_TEST_REDIS_URL is required for Redis integration tests")
    redis = Redis.from_url(redis_url, decode_responses=True)
    stream = "bili-ai-test-attempts"
    try:
        await redis.flushdb()
        now = datetime.now(UTC)
        decision = await repository.create_or_reuse_attempt(
            TargetKey("BV1redis", 250), "v1", now
        )
        dispatcher = OutboxDispatcher(
            session_factory,
            RedisStreamPublisher(redis, stream),
        )
        assert await dispatcher.dispatch_batch(limit=10) == 1
        first = await redis.xrange(stream)
        assert first[0][1]["idempotency_key"].endswith(":1:0")

        await redis.flushdb()
        recovered = await AttemptReconciler(session_factory).reconcile(
            now=now + timedelta(minutes=10),
            dispatch_timeout=timedelta(minutes=5),
        )
        assert recovered.redispatched == 1
        assert await dispatcher.dispatch_batch(limit=10) == 1
        second = await redis.xrange(stream)
        assert len(second) == 1
        assert second[0][1]["idempotency_key"] == (
            f"{decision.attempt.attempt_id}:1:1"
        )
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_expired_worker_is_requeued_and_old_message_is_fenced(
    repository: AnalysisRepository,
    session_factory: async_sessionmaker,
    engine: AsyncEngine,
) -> None:
    now = datetime.now(UTC)
    decision = await repository.create_or_reuse_attempt(TargetKey("BV1lease", 303), "v1", now)
    old_claim = await repository.claim_attempt(
        decision.attempt.attempt_id,
        decision.attempt.generation,
        decision.attempt.dispatch_epoch,
        60,
    )
    assert old_claim is not None
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE analysis_attempt SET lease_expires_at = :expired "
                "WHERE attempt_id = :attempt_id"
            ),
            {
                "expired": now - timedelta(seconds=1),
                "attempt_id": decision.attempt.attempt_id,
            },
        )

    recovered = await AttemptReconciler(session_factory).reconcile(
        now=now,
        dispatch_timeout=timedelta(minutes=5),
    )
    assert recovered.reclaimed == 1
    assert (
        await repository.claim_attempt(
            decision.attempt.attempt_id,
            decision.attempt.generation,
            decision.attempt.dispatch_epoch,
            60,
        )
        is None
    )
    new_claim = await repository.claim_attempt(
        decision.attempt.attempt_id,
        decision.attempt.generation + 1,
        decision.attempt.dispatch_epoch + 1,
        60,
    )
    assert new_claim is not None

    assert not await repository.fail_attempt(
        old_claim,
        "late_failure",
        now + timedelta(minutes=5),
    )
    async with engine.connect() as connection:
        status = await connection.scalar(
            text("SELECT status FROM analysis_attempt WHERE attempt_id = :attempt_id"),
            {"attempt_id": old_claim.attempt_id},
        )
    assert status == "fetching"

    stale_result = AnalysisResultWrite(
        score=10,
        label=LabelKey.LIGHT,
        confidence=0.8,
        evidence=(EvidenceItem(description="stale"),),
        analysis_version="v1",
        analyzed_at=now,
        analysis_expires_at=now + timedelta(days=1),
    )
    assert not await repository.complete_attempt(old_claim, stale_result)


@pytest.mark.asyncio
async def test_completed_and_failed_attempts_are_never_requeued(
    repository: AnalysisRepository,
    session_factory: async_sessionmaker,
) -> None:
    now = datetime.now(UTC)
    completed = await repository.create_or_reuse_attempt(TargetKey("BV1terminal", 401), "v1", now)
    completed_claim = await repository.claim_attempt(
        completed.attempt.attempt_id, completed.attempt.generation, 0, 60
    )
    assert completed_claim is not None
    assert await repository.complete_attempt(
        completed_claim,
        AnalysisResultWrite(
            score=80,
            label=LabelKey.HIGH,
            confidence=0.9,
            evidence=(),
            analysis_version="v1",
            analyzed_at=now,
            analysis_expires_at=now + timedelta(days=1),
        ),
    )

    failed = await repository.create_or_reuse_attempt(TargetKey("BV1terminal", 402), "v1", now)
    failed_claim = await repository.claim_attempt(
        failed.attempt.attempt_id, failed.attempt.generation, 0, 60
    )
    assert failed_claim is not None
    assert await repository.fail_attempt(
        failed_claim, "failed", now + timedelta(minutes=5)
    )

    recovered = await AttemptReconciler(session_factory).reconcile(
        now=now + timedelta(hours=1),
        dispatch_timeout=timedelta(minutes=5),
    )
    assert recovered.reclaimed == 0


@pytest.mark.asyncio
async def test_completion_constraint_failure_rolls_back_attempt_status(
    repository: AnalysisRepository,
    engine: AsyncEngine,
) -> None:
    now = datetime.now(UTC)
    decision = await repository.create_or_reuse_attempt(TargetKey("BV1rollback", 501), "v1", now)
    claim = await repository.claim_attempt(
        decision.attempt.attempt_id, decision.attempt.generation, 0, 60
    )
    assert claim is not None

    with pytest.raises(IntegrityError):
        await repository.complete_attempt(
            claim,
            AnalysisResultWrite(
                score=101,
                label=LabelKey.HIGH,
                confidence=0.9,
                evidence=(),
                analysis_version="v1",
                analyzed_at=now,
                analysis_expires_at=now + timedelta(days=1),
            ),
        )

    async with engine.connect() as connection:
        status = await connection.scalar(
            text("SELECT status FROM analysis_attempt WHERE attempt_id = :attempt_id"),
            {"attempt_id": decision.attempt.attempt_id},
        )
        result_count = await connection.scalar(
            text(
                "SELECT count(*) FROM analysis_result "
                "WHERE bvid = 'BV1rollback' AND cid = 501"
            )
        )
    assert status == "fetching"
    assert result_count == 0
