from __future__ import annotations

import argparse
import asyncio
import logging
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.db.repository import (
    AnalysisRepository,
    ClaimedAttempt,
    DeclarationWrite,
)
from app.detectors.openai_compatible import OpenAICompatibleDetector
from app.detectors.prompts import text_prompt, visual_prompt
from app.domain.types import DeclarationState, DetectorOutput
from app.integrations.bilibili.bcut import BCutClient
from app.integrations.bilibili.client import BilibiliClient, BilibiliUnavailableError
from app.integrations.bilibili.media import MediaAcquirer
from app.integrations.bilibili.metadata import MetadataService
from app.logging import configure_logging
from app.services.outbox import OutboxDispatcher, RedisStreamPublisher
from app.services.reconciliation import AttemptReconciler
from app.workers.pipeline import AcquiredMaterials, AnalysisPipeline
from app.workers.runner import RecoveryRuntime, RuntimeHealth, WorkerRunner

logger = logging.getLogger(__name__)


def _session_resources(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], Redis]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return engine, session_factory, redis


async def _load_materials(
    claim: ClaimedAttempt,
    workspace: Path,
    *,
    metadata_service: MetadataService,
    media: MediaAcquirer,
    bcut: BCutClient,
    repository: AnalysisRepository,
    declaration_ttl: timedelta,
) -> AcquiredMaterials:
    bvid = claim.target.bvid
    checked_at = datetime.now(UTC)
    metadata = await metadata_service.load(bvid, checked_at)
    part = next((part for part in metadata.parts if part.cid == claim.target.cid), None)
    if part is None:
        raise BilibiliUnavailableError(
            f"cid {claim.target.cid} is not a current part of {bvid}"
        )
    declaration_text = metadata.declaration_text
    await repository.save_declaration(
        claim.target,
        DeclarationWrite(
            state=(
                DeclarationState.DECLARED_AI
                if declaration_text is not None
                else DeclarationState.NOT_DECLARED
            ),
            source=(
                "platform"
                if declaration_text == "platform cooperation declaration"
                else "description"
                if declaration_text is not None
                else None
            ),
            evidence=(
                {"text": declaration_text} if declaration_text is not None else None
            ),
            checked_at=checked_at,
            expires_at=checked_at + declaration_ttl,
        ),
    )
    transcript = await media.extract_subtitles(bvid, workspace, page=part.page)
    source = "subtitle"
    if not transcript:
        samples = await media.acquire_audio_samples(
            bvid,
            part.duration_seconds,
            workspace,
            page=part.page,
        )
        if samples:
            transcript = await bcut.transcribe_samples(samples)
            source = "sampled_asr"
        else:
            source = "metadata_only"
    frames = await media.sample_frames(
        bvid,
        part.duration_seconds,
        workspace,
        count=8,
        page=part.page,
    )
    return AcquiredMaterials(
        metadata=metadata,
        transcript=transcript,
        transcript_source=source,
        frames=frames,
    )


async def run_worker() -> None:
    settings = get_settings()
    if settings.bcut_api_base is None:
        raise RuntimeError("BILI_AI_BCUT_API_BASE is required for the worker")
    engine, session_factory, redis = _session_resources(settings)
    repository = AnalysisRepository(session_factory)
    media = MediaAcquirer(
        max_workspace_bytes=settings.media_workspace_max_bytes,
        command_timeout_seconds=settings.media_command_timeout_seconds,
    )
    bilibili_headers = BilibiliClient.headers(settings.bilibili_cookie)
    async with (
        httpx.AsyncClient(
            base_url="https://api.bilibili.com",
            headers=bilibili_headers,
            timeout=settings.bilibili_request_timeout_seconds,
        ) as bilibili_http,
        httpx.AsyncClient(
            base_url=settings.ai_api_base,
            headers=(
                {"Authorization": f"Bearer {settings.ai_api_key}"}
                if settings.ai_api_key
                else None
            ),
            timeout=settings.ai_request_timeout_seconds,
        ) as ai_client,
        httpx.AsyncClient(
            base_url=settings.bcut_api_base,
            timeout=settings.bcut_poll_timeout_seconds,
        ) as bcut_http,
    ):
        bilibili = BilibiliClient(
            bilibili_http,
            max_retries=settings.bilibili_max_retries,
        )
        metadata_service = MetadataService(bilibili, session_factory)
        detector = OpenAICompatibleDetector(
            ai_client,
            model=settings.ai_model,
            max_evidence_items=settings.ai_max_evidence_items,
        )
        bcut = BCutClient(
            bcut_http,
            timeout_seconds=float(settings.bcut_poll_timeout_seconds),
        )

        async def material_loader(
            claim: ClaimedAttempt, workspace: Path
        ) -> AcquiredMaterials:
            return await _load_materials(
                claim,
                workspace,
                metadata_service=metadata_service,
                media=media,
                bcut=bcut,
                repository=repository,
                declaration_ttl=timedelta(days=settings.declaration_ttl_days),
            )

        async def text_detector(material: str, factor: float) -> DetectorOutput:
            return await detector.detect_text(text_prompt(material), factor)

        async def visual_detector(
            frames: tuple[Path, ...], factor: float
        ) -> DetectorOutput:
            return await detector.detect_visual(
                visual_prompt(len(frames)),
                frames,
                factor,
            )

        pipeline = AnalysisPipeline(
            repository,
            material_loader,
            text_detector,
            visual_detector,
            temp_root=settings.media_temp_root,
            result_ttl=timedelta(days=settings.analysis_ttl_days),
        )
        runner = WorkerRunner(
            redis,
            repository,
            pipeline,
            consumer=f"worker-{socket.gethostname()}",
            job_timeout_seconds=settings.analysis_task_timeout_seconds,
            failure_cooldown=timedelta(
                minutes=settings.failed_attempt_cooldown_minutes
            ),
        )
        try:
            logger.info("worker started", extra={"stage": "worker_start"})
            await runner.run_forever()
        finally:
            await redis.aclose()
            await engine.dispose()


async def run_dispatcher() -> None:
    settings = get_settings()
    engine, session_factory, redis = _session_resources(settings)
    publisher = RedisStreamPublisher(redis, "analysis-attempts")
    health = RuntimeHealth()
    runtime = RecoveryRuntime(
        OutboxDispatcher(session_factory, publisher),
        AttemptReconciler(session_factory),
        health,
    )
    try:
        logger.info("dispatcher started", extra={"stage": "dispatcher_start"})
        await asyncio.gather(runtime.dispatch_forever(), runtime.reconcile_forever())
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Bilibili AI analysis process entrypoints")
    parser.add_argument(
        "role",
        choices=("api", "dispatcher", "worker"),
        help="Process role to start",
    )
    args = parser.parse_args()
    if args.role == "api":
        import uvicorn

        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_config=None)
        return
    if args.role == "dispatcher":
        asyncio.run(run_dispatcher())
        return
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
