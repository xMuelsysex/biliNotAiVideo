from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.db.repository import ClaimedAttempt
from app.domain.types import DetectorKind, DetectorOutput, EvidenceItem, TargetKey
from app.integrations.bilibili.media import TranscriptSegment
from app.integrations.bilibili.metadata import VideoMetadata, VideoPart
from app.workers.pipeline import AcquiredMaterials, AnalysisPipeline


class RecordingRepository:
    def __init__(self, completed: bool = True) -> None:
        self.completed = completed
        self.result = None
        self.analyzing_calls = 0

    async def start_analyzing(self, claim):
        del claim
        self.analyzing_calls += 1
        return True

    async def complete_attempt(self, claim, result):
        self.result = result
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


def _metadata() -> VideoMetadata:
    return VideoMetadata(
        bvid="BV1Q541167Qg",
        title="AI generated animation",
        description="AI生成",
        tags=("AIGC",),
        parts=(VideoPart(1, 1, "part", 120),),
        default_cid=1,
        duration_seconds=120,
        declaration_text="creator declaration",
    )


@pytest.mark.asyncio
async def test_pipeline_aggregates_partial_detector_failure_and_cleans(tmp_path: Path) -> None:
    repository = RecordingRepository()
    workspaces: list[Path] = []

    async def loader(claim, workspace):
        workspaces.append(workspace)
        (workspace / "frame.jpg").write_bytes(b"image")
        return AcquiredMaterials(
            metadata=_metadata(),
            transcript=(TranscriptSegment(0, 1, "concrete evidence"),),
            transcript_source="sampled_asr",
            frames=tuple(workspace / f"frame-{index}.jpg" for index in range(6)),
        )

    async def text_detector(material, factor):
        return DetectorOutput(
            kind=DetectorKind.TEXT,
            score=0.8,
            confidence=0.9,
            material_factor=factor,
            evidence=(EvidenceItem(description="text evidence"),),
        )

    async def visual_detector(frames, factor):
        raise TimeoutError("visual timeout")

    pipeline = AnalysisPipeline(
        repository,
        loader,
        text_detector,
        visual_detector,
        temp_root=str(tmp_path),
    )
    assert await pipeline.run_analysis(_claim())
    assert repository.analyzing_calls == 1
    assert repository.result is not None
    assert repository.result.label is not None
    assert any(
        "visual detector unavailable" in item.description
        for item in repository.result.evidence
    )
    assert not workspaces[0].exists()


@pytest.mark.asyncio
async def test_low_evidence_returns_no_label_and_stale_write_is_visible(tmp_path: Path) -> None:
    repository = RecordingRepository(completed=False)

    async def loader(claim, workspace):
        return AcquiredMaterials(
            metadata=VideoMetadata(
                bvid="BV1Q541167Qg",
                title="ordinary",
                description="ordinary",
                tags=(),
                parts=(VideoPart(1, 1, "part", 10),),
                default_cid=1,
                duration_seconds=10,
                declaration_text=None,
            ),
            transcript=(),
            transcript_source="metadata_only",
            frames=(),
            metadata_complete=False,
        )

    async def weak(kind):
        return DetectorOutput(
            kind=kind,
            score=0.2,
            confidence=0.2,
            material_factor=0.1,
            evidence=(),
        )

    pipeline = AnalysisPipeline(
        repository,
        loader,
        lambda material, factor: weak(DetectorKind.TEXT),
        lambda frames, factor: weak(DetectorKind.VISUAL),
        temp_root=str(tmp_path),
    )
    assert not await pipeline.run_analysis(_claim())
    assert repository.result.label is None
    assert repository.result.confidence < 0.4
