import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.db.repository import ClaimedAttempt
from app.domain.types import DetectorKind, DetectorOutput, EvidenceItem, TargetKey
from app.integrations.bilibili.media import (
    MediaCleanupError,
    TranscriptSegment,
    task_workspace,
)
from app.integrations.bilibili.metadata import VideoMetadata, VideoPart
from app.workers.pipeline import AcquiredMaterials, AnalysisPipeline


class RecordingRepository:
    def __init__(self, completed: bool = True) -> None:
        self.completed = completed
        self.calls = 0

    async def start_analyzing(self, claim: ClaimedAttempt) -> bool:
        del claim
        return True

    async def complete_attempt(self, claim: ClaimedAttempt, result: object) -> bool:
        del claim, result
        self.calls += 1
        return self.completed


def _claim() -> ClaimedAttempt:
    return ClaimedAttempt(
        attempt_id=uuid4(),
        target=TargetKey("BV1Q541167Qg", 1),
        analysis_version="v1",
        generation=1,
        dispatch_epoch=0,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def _materials(workspace: Path) -> AcquiredMaterials:
    for index in range(6):
        (workspace / f"frame-{index}.jpg").write_bytes(b"frame")
    return AcquiredMaterials(
        metadata=VideoMetadata(
            bvid="BV1Q541167Qg",
            title="sample",
            description="sample",
            tags=("tag",),
            parts=(VideoPart(1, 1, "part", 60),),
            default_cid=1,
            duration_seconds=60,
            declaration_text=None,
        ),
        transcript=(TranscriptSegment(0, 1, "evidence text"),),
        transcript_source="subtitle",
        frames=tuple(workspace / f"frame-{index}.jpg" for index in range(6)),
    )


@pytest.mark.asyncio
async def test_workspace_removed_after_success(tmp_path: Path) -> None:
    repository = RecordingRepository(completed=True)
    workspaces: list[Path] = []

    async def loader(claim: ClaimedAttempt, workspace: Path) -> AcquiredMaterials:
        del claim
        workspaces.append(workspace)
        return _materials(workspace)

    async def detector(material: object, factor: float) -> DetectorOutput:
        del material
        return DetectorOutput(
            kind=DetectorKind.TEXT,
            score=0.8,
            confidence=0.9,
            material_factor=factor,
            evidence=(EvidenceItem(description="ok"),),
        )

    pipeline = AnalysisPipeline(
        repository,
        loader,
        detector,
        lambda frames, factor: detector(frames, factor),
        temp_root=str(tmp_path),
    )
    assert await pipeline.run_analysis(_claim())
    assert workspaces
    assert not workspaces[0].exists()


@pytest.mark.asyncio
async def test_workspace_removed_after_detector_failure(tmp_path: Path) -> None:
    repository = RecordingRepository(completed=True)
    workspaces: list[Path] = []

    async def loader(claim: ClaimedAttempt, workspace: Path) -> AcquiredMaterials:
        del claim
        workspaces.append(workspace)
        return _materials(workspace)

    async def text_detector(material: object, factor: float) -> DetectorOutput:
        del material, factor
        raise TimeoutError("text timeout")

    async def visual_detector(frames: object, factor: float) -> DetectorOutput:
        del frames, factor
        raise RuntimeError("visual crash")

    pipeline = AnalysisPipeline(
        repository,
        loader,
        text_detector,
        visual_detector,
        temp_root=str(tmp_path),
    )
    assert await pipeline.run_analysis(_claim())
    assert not workspaces[0].exists()


@pytest.mark.asyncio
async def test_cleanup_failure_blocks_completed_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = RecordingRepository(completed=True)

    async def loader(claim: ClaimedAttempt, workspace: Path) -> AcquiredMaterials:
        del claim
        return _materials(workspace)

    async def detector(material: object, factor: float) -> DetectorOutput:
        del material
        return DetectorOutput(
            kind=DetectorKind.TEXT,
            score=0.8,
            confidence=0.9,
            material_factor=factor,
            evidence=(EvidenceItem(description="ok"),),
        )

    def fail_cleanup(path: Path) -> None:
        del path
        raise PermissionError("denied")

    monkeypatch.setattr("app.integrations.bilibili.media.shutil.rmtree", fail_cleanup)
    pipeline = AnalysisPipeline(
        repository,
        loader,
        detector,
        lambda frames, factor: detector(frames, factor),
        temp_root=str(tmp_path),
    )
    with pytest.raises(MediaCleanupError, match="failed to remove"):
        await pipeline.run_analysis(_claim())
    assert repository.calls == 0


@pytest.mark.asyncio
async def test_pipeline_workspace_removed_after_timeout(tmp_path: Path) -> None:
    workspaces: list[Path] = []
    started = asyncio.Event()

    async def loader(claim: ClaimedAttempt, workspace: Path) -> AcquiredMaterials:
        del claim
        workspaces.append(workspace)
        (workspace / "media.bin").write_bytes(b"raw")
        started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    async def detector(material: object, factor: float) -> DetectorOutput:
        del material, factor
        raise AssertionError("detector must not run")

    pipeline = AnalysisPipeline(
        RecordingRepository(),
        loader,
        detector,
        lambda frames, factor: detector(frames, factor),
        temp_root=str(tmp_path),
    )
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(pipeline.run_analysis(_claim()), timeout=0.01)
    assert started.is_set()
    assert workspaces
    assert not workspaces[0].exists()


@pytest.mark.asyncio
async def test_pipeline_workspace_removed_after_worker_cancellation(tmp_path: Path) -> None:
    workspaces: list[Path] = []
    started = asyncio.Event()

    async def loader(claim: ClaimedAttempt, workspace: Path) -> AcquiredMaterials:
        del claim
        workspaces.append(workspace)
        (workspace / "media.bin").write_bytes(b"raw")
        started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    async def detector(material: object, factor: float) -> DetectorOutput:
        del material, factor
        raise AssertionError("detector must not run")

    pipeline = AnalysisPipeline(
        RecordingRepository(),
        loader,
        detector,
        lambda frames, factor: detector(frames, factor),
        temp_root=str(tmp_path),
    )
    task = asyncio.create_task(pipeline.run_analysis(_claim()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert workspaces
    assert not workspaces[0].exists()


@pytest.mark.asyncio
async def test_task_workspace_cleans_on_cancel(tmp_path: Path) -> None:
    workspaces: list[Path] = []

    async def body() -> None:
        async with task_workspace(str(tmp_path)) as workspace:
            workspaces.append(workspace)
            (workspace / "media.bin").write_bytes(b"raw")
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await body()
    assert workspaces
    assert not workspaces[0].exists()
