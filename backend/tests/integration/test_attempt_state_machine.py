import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.repository import AnalysisRepository, AnalysisResultWrite, ClaimedAttempt
from app.domain.types import EvidenceItem, LabelKey, TargetKey

BACKEND_ROOT = Path(__file__).parents[2]


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
async def repository(engine: AsyncEngine) -> AnalysisRepository:
    return AnalysisRepository(async_sessionmaker(engine, expire_on_commit=False))


def _result(version: str, score: int, now: datetime) -> AnalysisResultWrite:
    return AnalysisResultWrite(
        score=score,
        label=LabelKey.HIGH,
        confidence=0.9,
        evidence=(EvidenceItem(description=f"evidence-{version}"),),
        analysis_version=version,
        analyzed_at=now,
        analysis_expires_at=now + timedelta(days=1),
    )


@pytest.mark.asyncio
async def test_twenty_concurrent_creates_share_one_attempt(
    repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    target = TargetKey("BV1concurrent", 101)
    now = datetime.now(UTC)

    decisions = await asyncio.gather(
        *(repository.create_or_reuse_attempt(target, "v1", now) for _ in range(20))
    )

    assert sum(decision.created for decision in decisions) == 1
    assert len({decision.attempt.attempt_id for decision in decisions}) == 1
    async with engine.connect() as connection:
        attempts = await connection.scalar(
            text(
                "SELECT count(*) FROM analysis_attempt "
                "WHERE bvid = :bvid AND cid = :cid"
            ),
            {"bvid": target.bvid, "cid": target.cid},
        )
        events = await connection.scalar(text("SELECT count(*) FROM analysis_outbox"))
    assert attempts == 1
    assert events == 1


@pytest.mark.asyncio
async def test_newer_version_fences_late_completion(
    repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    target = TargetKey("BV1fencing", 202)
    now = datetime.now(UTC)
    v1 = await repository.create_or_reuse_attempt(target, "v1", now)
    v1_claim = await repository.claim_attempt(
        v1.attempt.attempt_id, v1.attempt.generation, 0, 120
    )
    assert v1_claim is not None

    v2 = await repository.create_or_reuse_attempt(target, "v2", now)
    v2_claim = await repository.claim_attempt(
        v2.attempt.attempt_id, v2.attempt.generation, 0, 120
    )
    assert v2_claim is not None
    assert await repository.complete_attempt(v2_claim, _result("v2", 90, now))
    assert not await repository.complete_attempt(v1_claim, _result("v1", 10, now))

    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT analysis_version, score FROM analysis_result "
                    "WHERE bvid = :bvid AND cid = :cid"
                ),
                {"bvid": target.bvid, "cid": target.cid},
            )
        ).mappings().one()
    assert row == {"analysis_version": "v2", "score": 90}


@pytest.mark.asyncio
async def test_failed_replacement_preserves_success_and_enforces_cooldown(
    repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    target = TargetKey("BV1cooldown", 303)
    now = datetime.now(UTC)
    v1 = await repository.create_or_reuse_attempt(target, "v1", now)
    v1_claim = await repository.claim_attempt(
        v1.attempt.attempt_id, v1.attempt.generation, 0, 120
    )
    assert v1_claim is not None
    assert await repository.complete_attempt(v1_claim, _result("v1", 70, now))

    v2 = await repository.create_or_reuse_attempt(target, "v2", now)
    v2_claim = await repository.claim_attempt(
        v2.attempt.attempt_id, v2.attempt.generation, 0, 120
    )
    assert v2_claim is not None
    retry_after = now + timedelta(minutes=10)
    assert await repository.fail_attempt(v2_claim, "download_failed", retry_after)

    cooldown = await repository.create_or_reuse_attempt(target, "v2", now + timedelta(minutes=1))
    assert not cooldown.created
    assert cooldown.cooldown
    assert cooldown.attempt.attempt_id == v2.attempt.attempt_id

    async with engine.connect() as connection:
        result_version = await connection.scalar(
            text(
                "SELECT analysis_version FROM analysis_result "
                "WHERE bvid = :bvid AND cid = :cid"
            ),
            {"bvid": target.bvid, "cid": target.cid},
        )
        attempt_count = await connection.scalar(
            text(
                "SELECT count(*) FROM analysis_attempt "
                "WHERE bvid = :bvid AND cid = :cid"
            ),
            {"bvid": target.bvid, "cid": target.cid},
        )
    assert result_version == "v1"
    assert attempt_count == 2


@pytest.mark.asyncio
async def test_heartbeat_requires_current_generation_and_live_lease(
    repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    target = TargetKey("BV1heartbeat", 325)
    now = datetime.now(UTC)
    decision = await repository.create_or_reuse_attempt(target, "v1", now)
    claim = await repository.claim_attempt(
        decision.attempt.attempt_id, decision.attempt.generation, 0, 60
    )
    assert claim is not None
    assert not await repository.start_analyzing(
        ClaimedAttempt(
            attempt_id=claim.attempt_id,
            target=claim.target,
            analysis_version=claim.analysis_version,
            generation=claim.generation + 1,
            dispatch_epoch=claim.dispatch_epoch,
            lease_expires_at=claim.lease_expires_at,
        )
    )
    assert await repository.start_analyzing(claim)
    assert not await repository.start_analyzing(claim)
    assert not await repository.heartbeat(
        claim.attempt_id, claim.generation + 1, 60
    )
    assert await repository.heartbeat(claim.attempt_id, claim.generation, 60)

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE analysis_attempt SET lease_expires_at = :expired "
                "WHERE attempt_id = :attempt_id"
            ),
            {
                "expired": now - timedelta(seconds=1),
                "attempt_id": claim.attempt_id,
            },
        )
    assert not await repository.heartbeat(claim.attempt_id, claim.generation, 60)


@pytest.mark.asyncio
async def test_switching_versions_supersedes_old_owner_and_allows_switch_back(
    repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    target = TargetKey("BV1switch", 350)
    now = datetime.now(UTC)
    first_v1 = await repository.create_or_reuse_attempt(target, "v1", now)
    v2 = await repository.create_or_reuse_attempt(target, "v2", now)
    second_v1 = await repository.create_or_reuse_attempt(target, "v1", now)

    assert first_v1.attempt.attempt_id != second_v1.attempt.attempt_id
    assert second_v1.attempt.generation == v2.attempt.generation + 1
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT attempt_id, status, error_code FROM analysis_attempt "
                    "WHERE bvid = :bvid AND cid = :cid ORDER BY generation"
                ),
                {"bvid": target.bvid, "cid": target.cid},
            )
        ).mappings().all()
    assert [row["status"] for row in rows] == ["failed", "failed", "queued"]
    assert [row["error_code"] for row in rows[:2]] == ["superseded", "superseded"]


@pytest.mark.asyncio
async def test_stale_generation_and_dispatch_epoch_cannot_claim(
    repository: AnalysisRepository,
) -> None:
    target = TargetKey("BV1stale", 404)
    decision = await repository.create_or_reuse_attempt(target, "v1", datetime.now(UTC))

    assert (
        await repository.claim_attempt(
            decision.attempt.attempt_id,
            decision.attempt.generation + 1,
            decision.attempt.dispatch_epoch,
            60,
        )
        is None
    )
    assert (
        await repository.claim_attempt(
            decision.attempt.attempt_id,
            decision.attempt.generation,
            decision.attempt.dispatch_epoch + 1,
            60,
        )
        is None
    )
    assert (
        await repository.claim_attempt(
            decision.attempt.attempt_id,
            decision.attempt.generation,
            decision.attempt.dispatch_epoch,
            60,
        )
        is not None
    )
