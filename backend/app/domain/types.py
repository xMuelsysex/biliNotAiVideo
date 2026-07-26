from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_STRICT_IMMUTABLE_CONFIG = ConfigDict(
    frozen=True,
    extra="forbid",
    strict=True,
    revalidate_instances="always",
)


@dataclass(frozen=True, slots=True)
class TargetKey:
    bvid: str
    cid: int

    def __post_init__(self) -> None:
        if not self.bvid:
            raise ValueError("bvid must not be empty")
        if self.cid <= 0:
            raise ValueError("cid must be positive")


class DetectorKind(StrEnum):
    TEXT = "text"
    VISUAL = "visual"
    METADATA = "metadata"


class DeclarationState(StrEnum):
    DECLARED_AI = "declared_ai"
    NOT_DECLARED = "not_declared"
    UNKNOWN = "unknown"


class LabelKey(StrEnum):
    NO_OBVIOUS_AI = "none"
    LIGHT = "light"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceItem(BaseModel):
    model_config = _STRICT_IMMUTABLE_CONFIG

    description: str = Field(min_length=1)
    timestamp_seconds: float | None = Field(
        default=None,
        ge=0.0,
        allow_inf_nan=False,
    )
    frame_index: int | None = Field(default=None, ge=0)


class DetectorOutput(BaseModel):
    model_config = _STRICT_IMMUTABLE_CONFIG

    kind: DetectorKind = Field(strict=False)
    score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    material_factor: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    evidence: tuple[EvidenceItem, ...] = Field(default=(), strict=False)


class ScoreResult(BaseModel):
    model_config = _STRICT_IMMUTABLE_CONFIG

    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    label: LabelKey | None
    evidence_status: Literal["sufficient", "insufficient"]
