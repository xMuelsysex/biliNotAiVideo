from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    redispatched: int
    reclaimed: int


class AttemptReconciler:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reconcile(
        self,
        *,
        now: datetime,
        dispatch_timeout: timedelta,
        limit: int = 100,
    ) -> ReconciliationResult:
        if dispatch_timeout <= timedelta(0):
            raise ValueError("dispatch_timeout must be positive")
        if limit <= 0:
            raise ValueError("limit must be positive")

        async with self._session_factory() as session, session.begin():
            redispatched = await self._redispatch_queued(
                session,
                now=now,
                dispatch_before=now - dispatch_timeout,
                limit=limit,
            )
            reclaimed = await self._reclaim_expired(session, now=now, limit=limit)
        return ReconciliationResult(redispatched=redispatched, reclaimed=reclaimed)

    async def _redispatch_queued(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        dispatch_before: datetime,
        limit: int,
    ) -> int:
        rows = (
            await session.execute(
                text(
                    "SELECT a.attempt_id, a.generation, a.dispatch_epoch "
                    "FROM analysis_attempt AS a JOIN analysis_target AS t "
                    "ON t.bvid = a.bvid AND t.cid = a.cid "
                    "WHERE a.status = 'queued' "
                    "AND (a.lease_expires_at IS NULL OR a.lease_expires_at <= :now) "
                    "AND t.owner_attempt_id = a.attempt_id "
                    "AND t.write_generation = a.generation "
                    "AND NOT EXISTS (SELECT 1 FROM analysis_outbox AS pending "
                    "WHERE pending.attempt_id = a.attempt_id "
                    "AND pending.generation = a.generation "
                    "AND pending.dispatch_epoch = a.dispatch_epoch "
                    "AND pending.delivered_at IS NULL) "
                    "AND (SELECT max(sent.created_at) FROM analysis_outbox AS sent "
                    "WHERE sent.attempt_id = a.attempt_id "
                    "AND sent.generation = a.generation) <= :dispatch_before "
                    "ORDER BY a.created_at FOR UPDATE OF a SKIP LOCKED LIMIT :limit"
                ),
                {"dispatch_before": dispatch_before, "now": now, "limit": limit},
            )
        ).mappings().all()
        for row in rows:
            new_epoch = int(row["dispatch_epoch"]) + 1
            await session.execute(
                text(
                    "UPDATE analysis_attempt SET dispatch_epoch = :new_epoch, updated_at = :now "
                    "WHERE attempt_id = :attempt_id"
                ),
                {
                    "new_epoch": new_epoch,
                    "now": now,
                    "attempt_id": row["attempt_id"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO analysis_outbox "
                    "(event_id, attempt_id, generation, dispatch_epoch, created_at) "
                    "VALUES (:event_id, :attempt_id, :generation, :dispatch_epoch, :now)"
                ),
                {
                    "event_id": uuid4(),
                    "attempt_id": row["attempt_id"],
                    "generation": row["generation"],
                    "dispatch_epoch": new_epoch,
                    "now": now,
                },
            )
        return len(rows)

    async def _reclaim_expired(
        self, session: AsyncSession, *, now: datetime, limit: int
    ) -> int:
        rows = (
            await session.execute(
                text(
                    "SELECT a.attempt_id, a.bvid, a.cid, a.generation, a.dispatch_epoch "
                    "FROM analysis_attempt AS a JOIN analysis_target AS t "
                    "ON t.bvid = a.bvid AND t.cid = a.cid "
                    "WHERE a.status IN ('fetching', 'analyzing') "
                    "AND a.lease_expires_at <= :now AND t.owner_attempt_id = a.attempt_id "
                    "AND t.write_generation = a.generation "
                    "ORDER BY a.lease_expires_at FOR UPDATE OF a, t SKIP LOCKED LIMIT :limit"
                ),
                {"now": now, "limit": limit},
            )
        ).mappings().all()
        for row in rows:
            generation = int(row["generation"]) + 1
            dispatch_epoch = int(row["dispatch_epoch"]) + 1
            await session.execute(
                text(
                    "UPDATE analysis_target SET write_generation = :generation, updated_at = :now "
                    "WHERE bvid = :bvid AND cid = :cid AND owner_attempt_id = :attempt_id"
                ),
                {
                    "generation": generation,
                    "now": now,
                    "bvid": row["bvid"],
                    "cid": row["cid"],
                    "attempt_id": row["attempt_id"],
                },
            )
            await session.execute(
                text(
                    "UPDATE analysis_attempt SET generation = :generation, "
                    "dispatch_epoch = :dispatch_epoch, status = 'queued', heartbeat_at = NULL, "
                    "lease_expires_at = NULL, updated_at = :now WHERE attempt_id = :attempt_id"
                ),
                {
                    "generation": generation,
                    "dispatch_epoch": dispatch_epoch,
                    "now": now,
                    "attempt_id": row["attempt_id"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO analysis_outbox "
                    "(event_id, attempt_id, generation, dispatch_epoch, created_at) "
                    "VALUES (:event_id, :attempt_id, :generation, :dispatch_epoch, :now)"
                ),
                {
                    "event_id": uuid4(),
                    "attempt_id": row["attempt_id"],
                    "generation": generation,
                    "dispatch_epoch": dispatch_epoch,
                    "now": now,
                },
            )
        return len(rows)
