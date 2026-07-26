from app.domain.types import DetectorKind, DetectorOutput, EvidenceItem
from app.integrations.bilibili.metadata import VideoMetadata

_AI_MARKERS = ("ai生成", "ai 生成", "aigc", "人工智能生成", "stable diffusion", "midjourney")


def detect_metadata(metadata: VideoMetadata, material_factor: float = 1.0) -> DetectorOutput:
    text = " ".join((metadata.title, metadata.description, *metadata.tags)).lower()
    matches = tuple(marker for marker in _AI_MARKERS if marker in text)
    declared = metadata.declaration_text is not None
    score = 1.0 if declared else min(len(matches) * 0.35, 1.0)
    confidence = 1.0 if declared else 0.7 if matches else 0.5
    evidence = []
    if declared:
        evidence.append(EvidenceItem(description="creator or platform AI declaration"))
    evidence.extend(EvidenceItem(description=f"metadata marker: {marker}") for marker in matches)
    return DetectorOutput(
        kind=DetectorKind.METADATA,
        score=score,
        confidence=confidence,
        material_factor=material_factor,
        evidence=tuple(evidence),
    )
