from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status

from app.api.deps import require_installation
from app.api.schemas import (
    AnalysisResponse,
    AttemptErrorCode,
    BatchItem,
    BatchRequest,
    BatchResponse,
    DeclarationResponse,
    ResultResponse,
    TargetRequest,
)
from app.db.analysis_queries import AnalysisQueryRepository, AnalysisSnapshot
from app.db.repository import AnalysisRepository, CreationRejected
from app.domain.types import TargetKey
from app.services.freshness import FreshnessPolicy
from app.services.rate_limits import InstallationRateLimits
from app.services.tokens import AuthenticatedInstallation

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])
_PUBLIC_ATTEMPT_ERRORS: frozenset[AttemptErrorCode] = frozenset(
    {
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
    }
)


def _services(
    request: Request,
) -> tuple[
    AnalysisQueryRepository,
    AnalysisRepository,
    FreshnessPolicy,
    InstallationRateLimits,
    str,
]:
    return (
        cast(AnalysisQueryRepository, request.app.state.analysis_queries),
        cast(AnalysisRepository, request.app.state.analysis_repository),
        cast(FreshnessPolicy, request.app.state.freshness_policy),
        cast(InstallationRateLimits, request.app.state.rate_limits),
        cast(str, request.app.state.analysis_version),
    )


def _compose(
    snapshot: AnalysisSnapshot,
    policy: FreshnessPolicy,
    now: datetime,
    analysis_version: str,
) -> AnalysisResponse:
    result_status: Literal["missing", "current", "stale"] = "missing"
    result = None
    evidence: list[dict[str, object]] = []
    analyzed_at = None
    rule_version = None
    if snapshot.result is not None:
        result_status = (
            "stale"
            if snapshot.result["analysis_version"] != analysis_version
            else policy.result_status(
                snapshot.result["analyzed_at"],
                snapshot.result["analysis_expires_at"],
                now,
            )
        )
        result = ResultResponse(
            score=snapshot.result["score"],
            label=snapshot.result["label"],
            confidence=snapshot.result["confidence"],
            stale=result_status == "stale",
        )
        evidence = list(snapshot.result["evidence_json"])
        analyzed_at = snapshot.result["analyzed_at"]
        rule_version = snapshot.result["analysis_version"]

    declaration = None
    if snapshot.declaration is not None:
        declaration_status = policy.declaration_status(
            snapshot.declaration["declaration_checked_at"],
            snapshot.declaration["declaration_expires_at"],
            now,
        )
        declaration = DeclarationResponse(
            state=snapshot.declaration["declaration_state"],
            source=snapshot.declaration["declaration_source"],
            stale=declaration_status == "stale",
        )

    attempt_status: Literal["none", "queued", "fetching", "analyzing", "failed"] = "none"
    retry_after = None
    error_code: AttemptErrorCode | None = None
    if snapshot.attempt is not None:
        raw_status = snapshot.attempt["attempt_status"]
        if raw_status in {"queued", "fetching", "analyzing", "failed"}:
            attempt_status = raw_status
            retry_after = snapshot.attempt["retry_after"]
            raw_error = snapshot.attempt["error_code"]
            if attempt_status == "failed" and raw_error is not None:
                error_code = (
                    cast(AttemptErrorCode, raw_error)
                    if raw_error in _PUBLIC_ATTEMPT_ERRORS
                    else "analysis_failed"
                )

    return AnalysisResponse(
        bvid=snapshot.target.bvid,
        cid=snapshot.target.cid,
        result_status=result_status,
        attempt_status=attempt_status,
        declaration=declaration,
        result=result,
        evidence=evidence,
        analyzed_at=analyzed_at,
        rule_version=rule_version,
        retry_after=retry_after,
        error_code=error_code,
    )


async def _consume_query(
    installation: AuthenticatedInstallation, limits: InstallationRateLimits
) -> None:
    decision = await limits.consume_query(str(installation.token_id))
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "query_quota_exhausted"},
        )


@router.get("/{bvid}", response_model=AnalysisResponse)
async def get_analysis(
    request: Request,
    installation: Annotated[AuthenticatedInstallation, Depends(require_installation)],
    bvid: str = Path(pattern=r"^BV[1-9A-HJ-NP-Za-km-z]{10}$"),
    cid: int = Query(gt=0),
) -> AnalysisResponse:
    target = TargetRequest(bvid=bvid, cid=cid)
    queries, _, policy, limits, version = _services(request)
    await _consume_query(installation, limits)
    return _compose(
        await queries.get_snapshot(TargetKey(target.bvid, target.cid)),
        policy,
        datetime.now(UTC),
        version,
    )


@router.post("", response_model=AnalysisResponse)
async def create_analysis(
    request: Request,
    response_status: Response,
    target: TargetRequest,
    installation: Annotated[AuthenticatedInstallation, Depends(require_installation)],
) -> AnalysisResponse:
    queries, repository, policy, limits, version = _services(request)
    key = TargetKey(target.bvid, target.cid)
    now = datetime.now(UTC)
    snapshot = await queries.get_snapshot(key)
    response = _compose(snapshot, policy, now, version)
    if response.result_status == "current":
        return response
    attempt_matches_version = (
        snapshot.attempt is not None and snapshot.attempt["attempt_version"] == version
    )
    if attempt_matches_version and response.attempt_status in {
        "queued",
        "fetching",
        "analyzing",
    }:
        response_status.status_code = status.HTTP_202_ACCEPTED
        return response
    if (
        attempt_matches_version
        and response.attempt_status == "failed"
        and policy.cooldown_is_active(response.retry_after, now)
    ):
        return response

    quota_consumed = False

    async def authorize_creation() -> bool:
        nonlocal quota_consumed
        decision = await limits.consume_analysis_creation(str(installation.token_id))
        quota_consumed = decision.allowed
        return decision.allowed

    try:
        await repository.create_or_reuse_attempt(
            key,
            version,
            now,
            authorize_creation=authorize_creation,
        )
    except CreationRejected:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "analysis_quota_exhausted"},
        ) from None
    except BaseException:
        if quota_consumed:
            await limits.refund_analysis_creation(str(installation.token_id))
        raise
    response_status.status_code = status.HTTP_202_ACCEPTED
    return _compose(
        await queries.get_snapshot(key),
        policy,
        datetime.now(UTC),
        version,
    )


@router.post("/batch", response_model=BatchResponse)
async def batch_lookup(
    request: Request,
    batch: BatchRequest,
    installation: Annotated[AuthenticatedInstallation, Depends(require_installation)],
) -> BatchResponse:
    queries, _, policy, limits, version = _services(request)
    await _consume_query(installation, limits)
    rows = await queries.batch_current_defaults(
        batch.bvids,
        datetime.now(UTC),
        policy,
        version,
    )
    return BatchResponse(
        items=[
            BatchItem(
                bvid=row["bvid"],
                cid=row["cid"],
                score=row["score"],
                label=row["label"],
                confidence=row["confidence"],
                analyzed_at=row["analyzed_at"],
                rule_version=row["analysis_version"],
            )
            for row in rows
        ]
    )
