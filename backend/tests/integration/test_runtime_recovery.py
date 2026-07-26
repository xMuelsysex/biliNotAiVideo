import os
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.repository import AnalysisRepository
from app.domain.types import TargetKey
from app.services.outbox import OutboxDispatcher, RedisStreamPublisher
from app.workers.runner import WorkerRunner


class Pipeline:
    def __init__(self) -> None:
        self.claims = []

    async def run_analysis(self, claim):
        self.claims.append(claim)
        return True


@pytest.mark.asyncio
async def test_duplicate_redis_delivery_runs_once(engine) -> None:
    redis_url = os.getenv("BILI_AI_TEST_REDIS_URL")
    if redis_url is None:
        pytest.skip("BILI_AI_TEST_REDIS_URL is required")
    redis = Redis.from_url(redis_url, decode_responses=True)
    await redis.flushdb()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = AnalysisRepository(session_factory)
    decision = await repository.create_or_reuse_attempt(
        TargetKey("BV1runtime11", 901), "v1", datetime.now(UTC)
    )
    publisher = RedisStreamPublisher(redis, "runtime-attempts")
    await OutboxDispatcher(session_factory, publisher).dispatch_batch(limit=10)
    await redis.xadd(
        "runtime-attempts",
        {
            "attempt_id": str(decision.attempt.attempt_id),
            "generation": "1",
            "dispatch_epoch": "0",
            "idempotency_key": f"{decision.attempt.attempt_id}:1:0",
        },
    )
    pipeline = Pipeline()
    runner = WorkerRunner(
        redis,
        repository,
        pipeline,
        stream="runtime-attempts",
        group="runtime-workers",
        consumer="test-worker",
    )
    assert await runner.run_once(block_ms=1)
    assert not await runner.run_once(block_ms=1)
    assert len(pipeline.claims) == 1
    await redis.aclose()
