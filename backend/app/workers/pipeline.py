import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.db.repository import AnalysisRepository, AnalysisResultWrite, ClaimedAttempt
from app.detectors.metadata import detect_metadata
from app.domain.scoring import aggregate_detector_outputs
from app.domain.types import DetectorKind, DetectorOutput, EvidenceItem
from app.integrations.bilibili.media import TranscriptSegment, task_workspace
from app.integrations.bilibili.metadata import VideoMetadata


@dataclass(frozen=True, slots=True)
class AcquiredMaterials:
    metadata: VideoMetadata
    transcript: tuple[TranscriptSegment, ...]
    transcript_source: str
    frames: tuple[Path, ...]
    metadata_complete: bool = True


MaterialLoader = Callable[[ClaimedAttempt, Path], Awaitable[AcquiredMaterials]]
TextDetector = Callable[[str, float], Awaitable[DetectorOutput]]
VisualDetector = Callable[[tuple[Path, ...], float], Awaitable[DetectorOutput]]


class AnalysisPipeline:
    def __init__(
        self,
        repository: AnalysisRepository,
        material_loader: MaterialLoader,
        text_detector: TextDetector,
        visual_detector: VisualDetector,
        *,
        temp_root: str | None = None,
        result_ttl: timedelta = timedelta(days=14),
    ) -> None:
        self._repository = repository
        self._material_loader = material_loader
        self._text_detector = text_detector
        self._visual_detector = visual_detector
        self._temp_root = temp_root
        self._result_ttl = result_ttl

    async def run_analysis(self, claim: ClaimedAttempt) -> bool:
        result: AnalysisResultWrite
        async with task_workspace(self._temp_root) as workspace:
            materials = await self._material_loader(claim, workspace)
            if not await self._repository.start_analyzing(claim):
                return False
            outputs = [
                detect_metadata(
                    materials.metadata,
                    1.0 if materials.metadata_complete else 0.5,
                )
            ]
            outputs.extend(await self._run_independent_detectors(materials))
            score = aggregate_detector_outputs(outputs)
            evidence = tuple(item for output in outputs for item in output.evidence)
            analyzed_at = datetime.now(UTC)
            result = AnalysisResultWrite(
                score=score.score,
                label=score.label,
                confidence=score.confidence,
                evidence=evidence,
                analysis_version=claim.analysis_version,
                analyzed_at=analyzed_at,
                analysis_expires_at=analyzed_at + self._result_ttl,
            )
        return await self._repository.complete_attempt(claim, result)

    async def _run_independent_detectors(
        self, materials: AcquiredMaterials
    ) -> tuple[DetectorOutput, DetectorOutput]:
        text_factor = {"subtitle": 1.0, "sampled_asr": 0.7, "metadata_only": 0.3}.get(
            materials.transcript_source,
            0.0,
        )
        visual_factor = (
            1.0
            if len(materials.frames) >= 6
            else 0.6
            if len(materials.frames) >= 3
            else 0.0
        )
        text_material = "\n".join(segment.text for segment in materials.transcript)
        text_task = self._safe_detector(
            DetectorKind.TEXT,
            self._text_detector(text_material, text_factor),
            text_factor,
        )
        visual_task = self._safe_detector(
            DetectorKind.VISUAL,
            self._visual_detector(materials.frames, visual_factor),
            visual_factor,
        )
        return await asyncio.gather(text_task, visual_task)

    @staticmethod
    async def _safe_detector(
        kind: DetectorKind,
        request: Awaitable[DetectorOutput],
        material_factor: float,
    ) -> DetectorOutput:
        try:
            output = await request
            return DetectorOutput(
                kind=kind,
                score=output.score,
                confidence=output.confidence,
                material_factor=material_factor,
                evidence=output.evidence,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return DetectorOutput(
                kind=kind,
                score=0,
                confidence=0,
                material_factor=0,
                evidence=(
                    EvidenceItem(
                        description=f"{kind.value} detector unavailable: {type(error).__name__}"
                    ),
                ),
            )
