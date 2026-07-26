import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_BVID_PATTERN = re.compile(r"^BV[1-9A-HJ-NP-Za-km-z]{10}$")
AttemptErrorCode = Literal[
    "video_unavailable",
    "risk_control",
    "temporary_upstream_failure",
    "subtitle_unavailable",
    "audio_unavailable",
    "frame_extraction_failed",
    "detector_timeout",
    "evidence_insufficient",
    "cleanup_failed",
    "media_command_timeout",
    "workspace_limit_exceeded",
    "analysis_failed",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetRequest(StrictModel):
    bvid: str
    cid: int = Field(gt=0)

    @field_validator("bvid")
    @classmethod
    def validate_bvid(cls, value: str) -> str:
        if _BVID_PATTERN.fullmatch(value) is None:
            raise ValueError("invalid BV identifier")
        return value


class BatchRequest(StrictModel):
    bvids: list[str] = Field(min_length=1, max_length=30)

    @field_validator("bvids")
    @classmethod
    def validate_bvids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("bvids must be unique")
        for value in values:
            TargetRequest.validate_bvid(value)
        return values


class DeclarationResponse(StrictModel):
    state: Literal["declared_ai", "not_declared", "unknown"]
    stale: bool
    source: str | None = None


class ResultResponse(StrictModel):
    score: int
    label: Literal["none", "light", "medium", "high"] | None
    confidence: float
    stale: bool


class AnalysisResponse(StrictModel):
    bvid: str
    cid: int
    result_status: Literal["missing", "current", "stale"]
    attempt_status: Literal["none", "queued", "fetching", "analyzing", "failed"]
    declaration: DeclarationResponse | None
    result: ResultResponse | None
    evidence: list[dict[str, object]]
    analyzed_at: datetime | None
    rule_version: str | None
    retry_after: datetime | None
    error_code: AttemptErrorCode | None


class BatchItem(StrictModel):
    bvid: str
    cid: int
    score: int
    label: Literal["none", "light", "medium", "high"] | None
    confidence: float
    analyzed_at: datetime
    rule_version: str


class BatchResponse(StrictModel):
    items: list[BatchItem]
