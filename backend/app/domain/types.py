from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    model_config = ConfigDict(frozen=True)

    description: str = Field(min_length=1)


class DetectorOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: DetectorKind
    score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    material_factor: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    evidence: tuple[EvidenceItem, ...] = ()


class ScoreResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    label: LabelKey | None
    evidence_status: Literal["sufficient", "insufficient"]
