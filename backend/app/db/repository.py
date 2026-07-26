from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.types import DeclarationState, EvidenceItem, LabelKey, TargetKey

_ACTIVE_STATUSES = ("queued", "fetching", "analyzing")
CreationAuthorizer = Callable[[], Awaitable[bool]]


class CreationRejected(RuntimeError):
    """Raised when a caller denies creation after reuse checks complete."""


@dataclass(frozen=True, slots=True)
class AttemptState:
    attempt_id: UUID
    target: TargetKey
    analysis_version: str
    generation: int
    status: str
    dispatch_epoch: int
    retry_after: datetime | None


@dataclass(frozen=True, slots=True)
class CreateDecision:
    attempt: AttemptState
    created: bool
    cooldown: bool = False


@dataclass(frozen=True, slots=True)
class ClaimedAttempt:
    attempt_id: UUID
    target: TargetKey
    analysis_version: str
    generation: int
    dispatch_epoch: int
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class AnalysisResultWrite:
    score: int
    label: LabelKey | None
    confidence: float
    evidence: tuple[EvidenceItem, ...]
    analysis_version: str
    analyzed_at: datetime
    analysis_expires_at: datetime


@dataclass(frozen=True, slots=True)
class DeclarationWrite:
    state: DeclarationState
    source: str | None
    evidence: Mapping[str, object] | None
    checked_at: datetime
    expires_at: datetime


class AnalysisRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_or_reuse_attempt(
        self,
        target: TargetKey,
        version: str,
        now: datetime,
        authorize_creation: CreationAuthorizer | None = None,
    ) -> CreateDecision:
        if not version:
            raise ValueError("version must not be empty")

        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"{target.bvid}:{target.cid}"},
            )
            target_row = (
                await session.execute(
                    text(
                        "SELECT desired_analysis_version, write_generation, owner_attempt_id "
                        "FROM analysis_target WHERE bvid = :bvid AND cid = :cid FOR UPDATE"
                    ),
                    {"bvid": target.bvid, "cid": target.cid},
                )
            ).mappings().one_or_none()

            if target_row is not None:
                active = await self._find_attempt(
                    session,
                    target,
                    version,
                    "status IN ('queued', 'fetching', 'analyzing') "
                    "AND attempt_id = :owner_attempt_id",
                    {"owner_attempt_id": target_row["owner_attempt_id"]},
                )
                if active is not None:
                    return CreateDecision(attempt=active, created=False)

                failed = await self._find_attempt(
                    session,
                    target,
                    version,
                    "status = 'failed' AND retry_after > :now",
                    {"now": now},
                )
                if failed is not None:
                    return CreateDecision(attempt=failed, created=False, cooldown=True)

                generation = int(target_row["write_generation"]) + 1
                await session.execute(
                    text(
                        "UPDATE analysis_attempt SET status = 'failed', "
                        "error_code = 'superseded', retry_after = :now, updated_at = :now "
                        "WHERE attempt_id = :owner_attempt_id "
                        "AND status IN ('queued', 'fetching', 'analyzing')"
                    ),
                    {
                        "owner_attempt_id": target_row["owner_attempt_id"],
                        "now": now,
                    },
                )
            else:
                generation = 1
                await session.execute(
                    text(
                        "INSERT INTO analysis_target "
                        "(bvid, cid, desired_analysis_version, write_generation) "
                        "VALUES (:bvid, :cid, :version, :generation)"
                    ),
                    {
                        "bvid": target.bvid,
                        "cid": target.cid,
                        "version": version,
                        "generation": generation,
                    },
                )

            if authorize_creation is not None and not await authorize_creation():
                raise CreationRejected("analysis creation was not authorized")

            attempt_id = uuid4()
            event_id = uuid4()
            await session.execute(
                text(
                    "INSERT INTO analysis_attempt "
                    "(attempt_id, bvid, cid, analysis_version, generation, status, dispatch_epoch) "
                    "VALUES (:attempt_id, :bvid, :cid, :version, :generation, 'queued', 0)"
                ),
                {
                    "attempt_id": attempt_id,
                    "bvid": target.bvid,
                    "cid": target.cid,
                    "version": version,
                    "generation": generation,
                },
            )
            await session.execute(
                text(
                    "UPDATE analysis_target SET desired_analysis_version = :version, "
                    "write_generation = :generation, owner_attempt_id = :attempt_id, "
                    "updated_at = :now WHERE bvid = :bvid AND cid = :cid"
                ),
                {
                    "version": version,
                    "generation": generation,
                    "attempt_id": attempt_id,
                    "now": now,
                    "bvid": target.bvid,
                    "cid": target.cid,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO analysis_outbox "
                    "(event_id, attempt_id, generation, dispatch_epoch) "
                    "VALUES (:event_id, :attempt_id, :generation, 0)"
                ),
                {
                    "event_id": event_id,
                    "attempt_id": attempt_id,
                    "generation": generation,
                },
            )
            return CreateDecision(
                attempt=AttemptState(
                    attempt_id=attempt_id,
                    target=target,
                    analysis_version=version,
                    generation=generation,
                    status="queued",
                    dispatch_epoch=0,
                    retry_after=None,
                ),
                created=True,
            )

    async def claim_attempt(
        self,
        attempt_id: UUID,
        generation: int,
        dispatch_epoch: int,
        lease_seconds: int,
    ) -> ClaimedAttempt | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "UPDATE analysis_attempt AS a SET status = 'fetching', "
                        "heartbeat_at = now(), "
                        "lease_expires_at = now() + make_interval(secs => :lease_seconds), "
                        "updated_at = now() FROM analysis_target AS t "
                        "WHERE a.attempt_id = :attempt_id AND a.status = 'queued' "
                        "AND a.generation = :generation AND a.dispatch_epoch = :dispatch_epoch "
                        "AND (a.lease_expires_at IS NULL OR a.lease_expires_at <= now()) "
                        "AND t.bvid = a.bvid AND t.cid = a.cid "
                        "AND t.owner_attempt_id = a.attempt_id "
                        "AND t.write_generation = a.generation "
                        "RETURNING a.attempt_id, a.bvid, a.cid, a.analysis_version, "
                        "a.generation, a.dispatch_epoch, a.lease_expires_at"
                    ),
                    {
                        "attempt_id": attempt_id,
                        "generation": generation,
                        "dispatch_epoch": dispatch_epoch,
                        "lease_seconds": lease_seconds,
                    },
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            return self._claimed_from_row(cast(Mapping[str, Any], row))

    async def heartbeat(self, attempt_id: UUID, generation: int, lease_seconds: int) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE analysis_attempt AS a SET heartbeat_at = now(), "
                    "lease_expires_at = now() + make_interval(secs => :lease_seconds), "
                    "updated_at = now() FROM analysis_target AS t "
                    "WHERE a.attempt_id = :attempt_id AND a.generation = :generation "
                    "AND a.status IN ('fetching', 'analyzing') AND a.lease_expires_at > now() "
                    "AND t.bvid = a.bvid AND t.cid = a.cid "
                    "AND t.owner_attempt_id = a.attempt_id "
                    "AND t.write_generation = a.generation "
                    "RETURNING a.attempt_id"
                ),
                {
                    "attempt_id": attempt_id,
                    "generation": generation,
                    "lease_seconds": lease_seconds,
                },
            )
            return result.scalar_one_or_none() is not None

    async def start_analyzing(self, claim: ClaimedAttempt) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE analysis_attempt AS a SET status = 'analyzing', updated_at = now() "
                    "FROM analysis_target AS t WHERE a.attempt_id = :attempt_id "
                    "AND a.generation = :generation AND a.status = 'fetching' "
                    "AND a.lease_expires_at > now() "
                    "AND t.bvid = a.bvid AND t.cid = a.cid "
                    "AND t.owner_attempt_id = a.attempt_id "
                    "AND t.desired_analysis_version = :version "
                    "AND t.write_generation = a.generation "
                    "RETURNING a.attempt_id"
                ),
                {
                    "attempt_id": claim.attempt_id,
                    "generation": claim.generation,
                    "version": claim.analysis_version,
                },
            )
            return result.scalar_one_or_none() is not None

    async def complete_attempt(
        self, claim: ClaimedAttempt, result: AnalysisResultWrite
    ) -> bool:
        if result.analysis_version != claim.analysis_version:
            raise ValueError("result analysis_version must match the claim")

        async with self._session_factory() as session, session.begin():
            fenced = (
                await session.execute(
                    text(
                        "UPDATE analysis_attempt AS a SET status = 'completed', updated_at = now() "
                        "FROM analysis_target AS t WHERE a.attempt_id = :attempt_id "
                        "AND a.generation = :generation "
                        "AND a.status IN ('fetching', 'analyzing') "
                        "AND a.lease_expires_at > now() "
                        "AND t.bvid = a.bvid AND t.cid = a.cid "
                        "AND t.owner_attempt_id = a.attempt_id "
                        "AND t.desired_analysis_version = :version "
                        "AND t.write_generation = a.generation "
                        "RETURNING a.bvid, a.cid"
                    ),
                    {
                        "attempt_id": claim.attempt_id,
                        "generation": claim.generation,
                        "version": claim.analysis_version,
                    },
                )
            ).mappings().one_or_none()
            if fenced is None:
                return False

            await session.execute(
                text(
                    "INSERT INTO analysis_result "
                    "(bvid, cid, score, label, confidence, evidence_json, analysis_version, "
                    "analyzed_at, analysis_expires_at) VALUES "
                    "(:bvid, :cid, :score, :label, :confidence, CAST(:evidence AS jsonb), "
                    ":version, :analyzed_at, :expires_at) "
                    "ON CONFLICT (bvid, cid) DO UPDATE SET score = EXCLUDED.score, "
                    "label = EXCLUDED.label, confidence = EXCLUDED.confidence, "
                    "evidence_json = EXCLUDED.evidence_json, "
                    "analysis_version = EXCLUDED.analysis_version, "
                    "analyzed_at = EXCLUDED.analyzed_at, "
                    "analysis_expires_at = EXCLUDED.analysis_expires_at, updated_at = now()"
                ),
                {
                    "bvid": claim.target.bvid,
                    "cid": claim.target.cid,
                    "score": result.score,
                    "label": result.label.value if result.label is not None else None,
                    "confidence": result.confidence,
                    "evidence": self._evidence_json(result.evidence),
                    "version": result.analysis_version,
                    "analyzed_at": result.analyzed_at,
                    "expires_at": result.analysis_expires_at,
                },
            )
            return True

    async def fail_attempt(
        self, claim: ClaimedAttempt, error_code: str, retry_after: datetime
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE analysis_attempt AS a SET status = 'failed', error_code = :error_code, "
                    "retry_after = :retry_after, updated_at = now() FROM analysis_target AS t "
                    "WHERE a.attempt_id = :attempt_id AND a.generation = :generation "
                    "AND a.status IN ('fetching', 'analyzing') "
                    "AND a.lease_expires_at > now() "
                    "AND t.bvid = a.bvid AND t.cid = a.cid "
                    "AND t.owner_attempt_id = a.attempt_id "
                    "AND t.write_generation = a.generation "
                    "RETURNING a.attempt_id"
                ),
                {
                    "attempt_id": claim.attempt_id,
                    "generation": claim.generation,
                    "error_code": error_code,
                    "retry_after": retry_after,
                },
            )
            return result.scalar_one_or_none() is not None

    async def save_declaration(
        self, target: TargetKey, declaration: DeclarationWrite
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO video_declaration "
                    "(bvid, cid, state, source, evidence, checked_at, expires_at) VALUES "
                    "(:bvid, :cid, :state, :source, CAST(:evidence AS jsonb), "
                    ":checked_at, :expires_at) "
                    "ON CONFLICT (bvid, cid) DO UPDATE SET state = EXCLUDED.state, "
                    "source = EXCLUDED.source, evidence = EXCLUDED.evidence, "
                    "checked_at = EXCLUDED.checked_at, expires_at = EXCLUDED.expires_at"
                ),
                {
                    "bvid": target.bvid,
                    "cid": target.cid,
                    "state": declaration.state.value,
                    "source": declaration.source,
                    "evidence": self._json_mapping(declaration.evidence),
                    "checked_at": declaration.checked_at,
                    "expires_at": declaration.expires_at,
                },
            )

    async def _find_attempt(
        self,
        session: AsyncSession,
        target: TargetKey,
        version: str,
        condition: str,
        extra_parameters: Mapping[str, object] | None = None,
    ) -> AttemptState | None:
        parameters: dict[str, object] = {
            "bvid": target.bvid,
            "cid": target.cid,
            "version": version,
        }
        parameters.update(extra_parameters or {})
        row = (
            await session.execute(
                text(
                    "SELECT attempt_id, bvid, cid, analysis_version, generation, status, "
                    "dispatch_epoch, retry_after FROM analysis_attempt "
                    "WHERE bvid = :bvid AND cid = :cid AND analysis_version = :version "
                    f"AND {condition} ORDER BY created_at DESC LIMIT 1"
                ),
                parameters,
            )
        ).mappings().one_or_none()
        if row is None:
            return None
        return self._attempt_from_row(cast(Mapping[str, Any], row))

    @staticmethod
    def _attempt_from_row(row: Mapping[str, Any]) -> AttemptState:
        return AttemptState(
            attempt_id=row["attempt_id"],
            target=TargetKey(bvid=row["bvid"], cid=row["cid"]),
            analysis_version=row["analysis_version"],
            generation=row["generation"],
            status=row["status"],
            dispatch_epoch=row["dispatch_epoch"],
            retry_after=row["retry_after"],
        )

    @staticmethod
    def _claimed_from_row(row: Mapping[str, Any]) -> ClaimedAttempt:
        return ClaimedAttempt(
            attempt_id=row["attempt_id"],
            target=TargetKey(bvid=row["bvid"], cid=row["cid"]),
            analysis_version=row["analysis_version"],
            generation=row["generation"],
            dispatch_epoch=row["dispatch_epoch"],
            lease_expires_at=row["lease_expires_at"],
        )

    @staticmethod
    def _evidence_json(evidence: tuple[EvidenceItem, ...]) -> str:
        import json

        return json.dumps([item.model_dump(mode="json") for item in evidence])

    @staticmethod
    def _json_mapping(value: Mapping[str, object] | None) -> str:
        import json

        return json.dumps(value)
