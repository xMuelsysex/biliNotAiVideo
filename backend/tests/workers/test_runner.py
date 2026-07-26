import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.db.repository import ClaimedAttempt
from app.domain.types import TargetKey
from app.workers.runner import WorkerRunner


class FakeRedis:
    def __init__(self, fields=None) -> None:
        self.fields = fields
        self.acked = []

    async def xgroup_create(self, *args, **kwargs):
        return True

    async def xreadgroup(self, *args, **kwargs):
        if self.fields is None:
            return []
        fields, self.fields = self.fields, None
        return [("stream", [("message-1", fields)])]

    async def xack(self, stream, group, message):
        self.acked.append(message)

    async def xlen(self, stream):
        return 0


class FakeRepository:
    def __init__(self, claim, *, failure_persisted: bool = True) -> None:
        self.claim = claim
        self.failure_persisted = failure_persisted
        self.heartbeats = 0
        self.failures: list[tuple[str, datetime]] = []

    async def claim_attempt(self, *args):
        return self.claim

    async def heartbeat(self, *args):
        self.heartbeats += 1
        return True

    async def fail_attempt(self, claim, error_code, retry_after):
        assert claim == self.claim
        self.failures.append((error_code, retry_after))
        return self.failure_persisted


class Pipeline:
    def __init__(self) -> None:
        self.runs = 0

    async def run_analysis(self, claim):
        self.runs += 1
        await asyncio.sleep(0.02)
        return True


class FailingPipeline:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def run_analysis(self, claim):
        del claim
        raise self.error


class BlockingPipeline:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run_analysis(self, claim):
        del claim
        self.started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")


def _claim() -> ClaimedAttempt:
    return ClaimedAttempt(
        attempt_id=uuid4(),
        target=TargetKey("BV1Q541167Qg", 1),
        analysis_version="v1",
        generation=2,
        dispatch_epoch=3,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_runner_claims_full_key_heartbeats_and_acks() -> None:
    claim = _claim()
    redis = FakeRedis(
        {
            "attempt_id": str(claim.attempt_id),
            "generation": "2",
            "dispatch_epoch": "3",
        }
    )
    repository = FakeRepository(claim)
    pipeline = Pipeline()
    runner = WorkerRunner(
        redis,
        repository,
        pipeline,
        heartbeat_seconds=0.005,
    )
    assert await runner.run_once(block_ms=1)
    assert pipeline.runs == 1
    assert repository.heartbeats >= 1
    assert redis.acked == ["message-1"]
    assert runner.health.active_jobs == 0


@pytest.mark.asyncio
async def test_stale_delivery_is_acked_without_pipeline() -> None:
    claim = _claim()
    redis = FakeRedis(
        {
            "attempt_id": str(claim.attempt_id),
            "generation": "1",
            "dispatch_epoch": "0",
        }
    )
    pipeline = Pipeline()
    runner = WorkerRunner(redis, FakeRepository(None), pipeline)
    assert not await runner.run_once(block_ms=1)
    assert pipeline.runs == 0
    assert redis.acked == ["message-1"]


@pytest.mark.asyncio
async def test_runner_records_job_timeout_and_acknowledges() -> None:
    claim = _claim()
    redis = FakeRedis(
        {
            "attempt_id": str(claim.attempt_id),
            "generation": "2",
            "dispatch_epoch": "3",
        }
    )
    repository = FakeRepository(claim)
    runner = WorkerRunner(
        redis,
        repository,
        Pipeline(),
        job_timeout_seconds=0.001,
    )
    assert await runner.run_once(block_ms=1)
    assert repository.failures[0][0] == "detector_timeout"
    assert redis.acked == ["message-1"]
    assert runner.health.active_jobs == 0


@pytest.mark.asyncio
async def test_runner_maps_unknown_failure_and_acknowledges() -> None:
    claim = _claim()
    redis = FakeRedis(
        {
            "attempt_id": str(claim.attempt_id),
            "generation": "2",
            "dispatch_epoch": "3",
        }
    )
    repository = FakeRepository(claim)
    runner = WorkerRunner(redis, repository, FailingPipeline(RuntimeError("boom")))
    assert await runner.run_once(block_ms=1)
    assert repository.failures[0][0] == "analysis_failed"
    assert redis.acked == ["message-1"]


@pytest.mark.asyncio
async def test_runner_keeps_message_when_failure_transition_loses_fence() -> None:
    claim = _claim()
    redis = FakeRedis(
        {
            "attempt_id": str(claim.attempt_id),
            "generation": "2",
            "dispatch_epoch": "3",
        }
    )
    repository = FakeRepository(claim, failure_persisted=False)
    runner = WorkerRunner(redis, repository, FailingPipeline(RuntimeError("boom")))
    assert not await runner.run_once(block_ms=1)
    assert repository.failures[0][0] == "analysis_failed"
    assert redis.acked == []


@pytest.mark.asyncio
async def test_runner_cancellation_leaves_message_for_recovery() -> None:
    claim = _claim()
    redis = FakeRedis(
        {
            "attempt_id": str(claim.attempt_id),
            "generation": "2",
            "dispatch_epoch": "3",
        }
    )
    repository = FakeRepository(claim)
    pipeline = BlockingPipeline()
    runner = WorkerRunner(redis, repository, pipeline)
    task = asyncio.create_task(runner.run_once(block_ms=1))
    await pipeline.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert repository.failures == []
    assert redis.acked == []
    assert runner.health.active_jobs == 0


@pytest.mark.asyncio
async def test_run_forever_is_cancellation_safe() -> None:
    runner = WorkerRunner(FakeRedis(), FakeRepository(None), Pipeline())
    task = asyncio.create_task(runner.run_forever())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
