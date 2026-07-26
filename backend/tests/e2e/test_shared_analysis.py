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
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.repository import AnalysisRepository, AnalysisResultWrite
from app.domain.types import EvidenceItem, LabelKey, TargetKey
from app.main import create_app
from app.workers.runner import WorkerRunner

BACKEND_ROOT = Path(__file__).parents[2]


class OneMessageRedis:
    def __init__(self, fields: dict[str, str]) -> None:
        self.fields: dict[str, str] | None = fields
        self.acked: list[str] = []

    async def xgroup_create(self, *args: object, **kwargs: object) -> bool:
        return True

    async def xreadgroup(self, *args: object, **kwargs: object) -> list[object]:
        if self.fields is None:
            return []
        fields, self.fields = self.fields, None
        return [("stream", [("message-1", fields)])]

    async def xack(self, stream: str, group: str, message: str) -> None:
        del stream, group
        self.acked.append(message)

    async def xlen(self, stream: str) -> int:
        del stream
        return 0


class RiskControlError(RuntimeError):
    code = "risk_control"


class RiskControlPipeline:
    async def run_analysis(self, claim: object) -> bool:
        del claim
        raise RiskControlError("risk control")


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


@pytest_asyncio.fixture
async def repository(engine: AsyncEngine) -> AnalysisRepository:
    return AnalysisRepository(async_sessionmaker(engine, expire_on_commit=False))


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    del engine
    settings = Settings(
        database_url=_database_url(),
        redis_url=_redis_url(),
        allowed_extension_origins=["chrome-extension://abcdefghijklmnopabcdefghijklmnop"],
    )
    application = create_app(settings)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.mark.asyncio
async def test_ready_checks_postgres_and_redis(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
    }


async def _token(client: AsyncClient) -> str:
    response = await client.post("/api/v1/installations")
    assert response.status_code == 201
    return str(response.json()["token"])


def _result(version: str, score: int, now: datetime) -> AnalysisResultWrite:
    return AnalysisResultWrite(
        score=score,
        label=LabelKey.HIGH,
        confidence=0.9,
        evidence=(EvidenceItem(description=f"evidence-{version}"),),
        analysis_version=version,
        analyzed_at=now,
        analysis_expires_at=now + timedelta(days=14),
    )


@pytest.mark.asyncio
async def test_two_installations_share_one_completed_result(
    client: AsyncClient,
    repository: AnalysisRepository,
    engine: AsyncEngine,
) -> None:
    first = await _token(client)
    second = await _token(client)
    body = {"bvid": "BV1Q541167Qg", "cid": 1}
    created_a = await client.post(
        "/api/v1/analyses",
        json=body,
        headers={"Authorization": f"Bearer {first}"},
    )
    created_b = await client.post(
        "/api/v1/analyses",
        json=body,
        headers={"Authorization": f"Bearer {second}"},
    )
    assert created_a.status_code == 202
    assert created_b.status_code == 202
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT attempt_id,generation,dispatch_epoch "
                    "FROM analysis_attempt"
                )
            )
        ).mappings().one()
        attempts = await connection.scalar(text("SELECT COUNT(*) FROM analysis_attempt"))
        outbox = await connection.scalar(text("SELECT COUNT(*) FROM analysis_outbox"))
    assert attempts == 1
    assert outbox == 1

    claim = await repository.claim_attempt(
        row["attempt_id"],
        row["generation"],
        row["dispatch_epoch"],
        60,
    )
    assert claim is not None
    assert await repository.complete_attempt(
        claim,
        _result("v1", 86, datetime.now(UTC)),
    )
    shared_a = await client.get(
        "/api/v1/analyses/BV1Q541167Qg?cid=1",
        headers={"Authorization": f"Bearer {first}"},
    )
    shared_b = await client.get(
        "/api/v1/analyses/BV1Q541167Qg?cid=1",
        headers={"Authorization": f"Bearer {second}"},
    )
    assert shared_a.json()["result"] == shared_b.json()["result"]
    assert shared_a.json()["result"]["score"] == 86
    async with engine.connect() as connection:
        results = await connection.scalar(text("SELECT COUNT(*) FROM analysis_result"))
    assert results == 1


@pytest.mark.asyncio
async def test_later_client_reuses_completed_result_without_new_attempt(
    client: AsyncClient, repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    now = datetime.now(UTC)
    target = TargetKey("BV1mK4y1C7Bz", 2)
    decision = await repository.create_or_reuse_attempt(target, "v1", now)
    claim = await repository.claim_attempt(
        decision.attempt.attempt_id,
        decision.attempt.generation,
        decision.attempt.dispatch_epoch,
        60,
    )
    assert claim is not None
    assert await repository.complete_attempt(claim, _result("v1", 88, now))
    token = await _token(client)
    response = await client.post(
        "/api/v1/analyses",
        json={"bvid": target.bvid, "cid": target.cid},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result_status"] == "current"
    assert payload["result"]["score"] == 88
    async with engine.connect() as connection:
        attempts = await connection.scalar(text("SELECT COUNT(*) FROM analysis_attempt"))
        active = await connection.scalar(
            text(
                "SELECT COUNT(*) FROM analysis_attempt "
                "WHERE status IN ('queued','fetching','analyzing')"
            )
        )
        outbox = await connection.scalar(text("SELECT COUNT(*) FROM analysis_outbox"))
    assert attempts == 1
    assert active == 0
    assert outbox == 1


@pytest.mark.asyncio
async def test_worker_failure_reaches_public_error_contract(
    client: AsyncClient, engine: AsyncEngine, repository: AnalysisRepository
) -> None:
    token = await _token(client)
    created = await client.post(
        "/api/v1/analyses",
        json={"bvid": "BV1err111111", "cid": 7},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 202
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT attempt_id,generation,dispatch_epoch "
                    "FROM analysis_attempt WHERE bvid='BV1err111111' AND cid=7"
                )
            )
        ).mappings().one()
    redis = OneMessageRedis(
        {
            "attempt_id": str(row["attempt_id"]),
            "generation": str(row["generation"]),
            "dispatch_epoch": str(row["dispatch_epoch"]),
        }
    )
    runner = WorkerRunner(redis, repository, RiskControlPipeline())  # type: ignore[arg-type]
    assert await runner.run_once(block_ms=1)
    response = await client.get(
        "/api/v1/analyses/BV1err111111?cid=7",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["attempt_status"] == "failed"
    assert response.json()["error_code"] == "risk_control"
    assert response.json()["retry_after"] is not None
    assert redis.acked == ["message-1"]


@pytest.mark.asyncio
async def test_version_fencing_keeps_newer_owner(
    repository: AnalysisRepository, engine: AsyncEngine
) -> None:
    now = datetime.now(UTC)
    target = TargetKey("BV1xx411c7mD", 9)
    v1 = await repository.create_or_reuse_attempt(target, "v1", now)
    v1_claim = await repository.claim_attempt(
        v1.attempt.attempt_id, v1.attempt.generation, v1.attempt.dispatch_epoch, 60
    )
    v2 = await repository.create_or_reuse_attempt(target, "v2", now)
    v2_claim = await repository.claim_attempt(
        v2.attempt.attempt_id, v2.attempt.generation, v2.attempt.dispatch_epoch, 60
    )
    assert v1_claim is not None and v2_claim is not None
    assert await repository.complete_attempt(v2_claim, _result("v2", 91, now))
    assert not await repository.complete_attempt(v1_claim, _result("v1", 11, now))
    async with engine.connect() as connection:
        score = await connection.scalar(
            text("SELECT score FROM analysis_result WHERE bvid = :bvid AND cid = :cid"),
            {"bvid": target.bvid, "cid": target.cid},
        )
        version = await connection.scalar(
            text(
                "SELECT analysis_version FROM analysis_result "
                "WHERE bvid = :bvid AND cid = :cid"
            ),
            {"bvid": target.bvid, "cid": target.cid},
        )
    assert score == 91
    assert version == "v2"
