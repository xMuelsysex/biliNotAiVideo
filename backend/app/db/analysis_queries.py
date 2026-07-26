from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.types import TargetKey
from app.services.freshness import FreshnessPolicy


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    target: TargetKey
    result: Mapping[str, Any] | None
    declaration: Mapping[str, Any] | None
    attempt: Mapping[str, Any] | None


class AnalysisQueryRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_snapshot(self, target: TargetKey) -> AnalysisSnapshot:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT r.score, r.label, r.confidence, r.evidence_json, "
                        "r.analysis_version, r.analyzed_at, r.analysis_expires_at, "
                        "d.state AS declaration_state, d.source AS declaration_source, "
                        "d.checked_at AS declaration_checked_at, "
                        "d.expires_at AS declaration_expires_at, "
                        "a.status AS attempt_status, a.retry_after, a.error_code, "
                        "a.analysis_version AS attempt_version "
                        "FROM analysis_target AS t "
                        "LEFT JOIN analysis_result AS r ON r.bvid=t.bvid AND r.cid=t.cid "
                        "LEFT JOIN video_declaration AS d ON d.bvid=t.bvid AND d.cid=t.cid "
                        "LEFT JOIN analysis_attempt AS a ON a.attempt_id=t.owner_attempt_id "
                        "WHERE t.bvid=:bvid AND t.cid=:cid"
                    ),
                    {"bvid": target.bvid, "cid": target.cid},
                )
            ).mappings().one_or_none()
        if row is None:
            return AnalysisSnapshot(target, None, None, None)
        values = cast(Mapping[str, Any], row)
        result = None
        if values["analyzed_at"] is not None:
            result = values
        declaration = None
        if values["declaration_state"] is not None:
            declaration = values
        attempt = None
        if values["attempt_status"] is not None:
            attempt = values
        return AnalysisSnapshot(target, result, declaration, attempt)

    async def batch_current_defaults(
        self,
        bvids: list[str],
        now: datetime,
        policy: FreshnessPolicy,
        analysis_version: str,
    ) -> list[Mapping[str, Any]]:
        statement = text(
            "SELECT m.bvid, m.default_cid AS cid, r.score, r.label, r.confidence, "
            "r.analyzed_at, r.analysis_version FROM video_metadata AS m "
            "JOIN analysis_result AS r ON r.bvid=m.bvid AND r.cid=m.default_cid "
            "WHERE m.bvid IN :bvids AND m.checked_at > :metadata_after "
            "AND r.analysis_expires_at > :now "
            "AND r.analysis_version = :analysis_version ORDER BY m.bvid"
        ).bindparams(bindparam("bvids", expanding=True))
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    statement,
                    {
                        "bvids": bvids,
                        "metadata_after": now - policy.metadata_ttl,
                        "now": now,
                        "analysis_version": analysis_version,
                    },
                )
            ).mappings().all()
        return [cast(Mapping[str, Any], row) for row in rows]
