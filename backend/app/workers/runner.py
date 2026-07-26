import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis

from app.db.repository import AnalysisRepository, ClaimedAttempt
from app.services.outbox import OutboxDispatcher
from app.services.reconciliation import AttemptReconciler

logger = logging.getLogger(__name__)

_ATTEMPT_ERROR_CODES = frozenset(
    {
        "video_unavailable",
        "risk_control",
        "temporary_upstream_failure",
        "subtitle_unavailable",
        "audio_unavailable",
        "visual_unavailable",
        "detector_timeout",
        "evidence_insufficient",
        "cleanup_failed",
        "media_command_timeout",
        "workspace_limit_exceeded",
        "analysis_failed",
    }
)


def _attempt_error_code(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "detector_timeout"
    code = getattr(error, "code", None)
    return str(code) if code in _ATTEMPT_ERROR_CODES else "analysis_failed"


class Pipeline(Protocol):
    async def run_analysis(self, claim: ClaimedAttempt) -> bool: ...


@dataclass(slots=True)
class RuntimeHealth:
    last_dispatch_at: datetime | None = None
    last_reconciliation_at: datetime | None = None
    active_jobs: int = 0
    queue_depth: int = 0


class WorkerRunner:
    def __init__(
        self,
        redis: Redis,
        repository: AnalysisRepository,
        pipeline: Pipeline,
        *,
        stream: str = "analysis-attempts",
        group: str = "analysis-workers",
        consumer: str = "worker-1",
        lease_seconds: int = 60,
        heartbeat_seconds: float = 20,
        job_timeout_seconds: float = 900,
        failure_cooldown: timedelta = timedelta(minutes=10),
    ) -> None:
        if job_timeout_seconds <= 0:
            raise ValueError("job_timeout_seconds must be positive")
        if failure_cooldown <= timedelta(0):
            raise ValueError("failure_cooldown must be positive")
        self._redis = redis
        self._repository = repository
        self._pipeline = pipeline
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._job_timeout_seconds = job_timeout_seconds
        self._failure_cooldown = failure_cooldown
        self.health = RuntimeHealth()

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                self._stream, self._group, id="0", mkstream=True
            )
        except Exception as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def run_once(self, block_ms: int = 1000) -> bool:
        await self.ensure_group()
        messages = await self._redis.xreadgroup(
            self._group,
            self._consumer,
            {self._stream: ">"},
            count=1,
            block=block_ms,
        )
        if not messages:
            self.health.queue_depth = int(await self._redis.xlen(self._stream))
            return False
        _, entries = messages[0]
        message_id, fields = entries[0]
        claim = await self._repository.claim_attempt(
            UUID(fields["attempt_id"]),
            int(fields["generation"]),
            int(fields["dispatch_epoch"]),
            self._lease_seconds,
        )
        if claim is None:
            await self._redis.xack(self._stream, self._group, message_id)
            return False
        self.health.active_jobs += 1
        heartbeat = asyncio.create_task(self._heartbeat(claim))
        started = time.perf_counter()
        log_context = {
            "target": f"{claim.target.bvid}:{claim.target.cid}",
            "attempt_id": str(claim.attempt_id),
            "generation": claim.generation,
            "stage": "analysis",
        }
        logger.info("analysis started", extra=log_context)
        try:
            completed = await asyncio.wait_for(
                self._pipeline.run_analysis(claim),
                timeout=self._job_timeout_seconds,
            )
            logger.info(
                "analysis finished",
                extra={
                    **log_context,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error_code": None if completed else "stale_completion",
                },
            )
        except Exception as error:
            error_code = _attempt_error_code(error)
            failure_persisted = await self._repository.fail_attempt(
                claim,
                error_code,
                datetime.now(UTC) + self._failure_cooldown,
            )
            logger.exception(
                "analysis failed",
                extra={
                    **log_context,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error_code": error_code,
                },
            )
            if not failure_persisted:
                logger.warning(
                    "analysis failure lost ownership before terminal transition",
                    extra={**log_context, "error_code": error_code},
                )
                return False
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            self.health.active_jobs -= 1
        await self._redis.xack(self._stream, self._group, message_id)
        return True

    async def run_forever(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(0)

    async def _heartbeat(self, claim: ClaimedAttempt) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            renewed = await self._repository.heartbeat(
                claim.attempt_id,
                claim.generation,
                self._lease_seconds,
            )
            if not renewed:
                return


class RecoveryRuntime:
    def __init__(
        self,
        dispatcher: OutboxDispatcher,
        reconciler: AttemptReconciler,
        health: RuntimeHealth,
        *,
        dispatch_interval: float = 1,
        reconcile_interval: float = 30,
    ) -> None:
        self._dispatcher = dispatcher
        self._reconciler = reconciler
        self._health = health
        self._dispatch_interval = dispatch_interval
        self._reconcile_interval = reconcile_interval

    async def dispatch_forever(self) -> None:
        while True:
            await self._dispatcher.dispatch_batch(limit=100)
            self._health.last_dispatch_at = datetime.now(UTC)
            await asyncio.sleep(self._dispatch_interval)

    async def reconcile_forever(self, dispatch_timeout_seconds: int = 300) -> None:
        from datetime import timedelta

        while True:
            await self._reconciler.reconcile(
                now=datetime.now(UTC),
                dispatch_timeout=timedelta(seconds=dispatch_timeout_seconds),
            )
            self._health.last_reconciliation_at = datetime.now(UTC)
            await asyncio.sleep(self._reconcile_interval)
