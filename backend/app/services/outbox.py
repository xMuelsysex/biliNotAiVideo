from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class DispatchMessage:
    attempt_id: UUID
    generation: int
    dispatch_epoch: int

    @property
    def idempotency_key(self) -> str:
        return f"{self.attempt_id}:{self.generation}:{self.dispatch_epoch}"


class MessagePublisher(Protocol):
    async def publish(self, message: DispatchMessage) -> None: ...


class RedisStreamPublisher:
    def __init__(self, redis: Redis, stream_name: str) -> None:
        self._redis = redis
        self._stream_name = stream_name

    async def publish(self, message: DispatchMessage) -> None:
        await self._redis.xadd(
            self._stream_name,
            {
                "attempt_id": str(message.attempt_id),
                "generation": str(message.generation),
                "dispatch_epoch": str(message.dispatch_epoch),
                "idempotency_key": message.idempotency_key,
            },
        )


class OutboxDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: MessagePublisher,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher

    async def dispatch_batch(self, *, limit: int) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")

        dispatched = 0
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.execute(
                    text(
                        "SELECT event_id, attempt_id, generation, dispatch_epoch "
                        "FROM analysis_outbox WHERE delivered_at IS NULL "
                        "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT :limit"
                    ),
                    {"limit": limit},
                )
            ).mappings()
            for raw_row in rows:
                row = cast(Mapping[str, object], raw_row)
                message = DispatchMessage(
                    attempt_id=cast(UUID, row["attempt_id"]),
                    generation=cast(int, row["generation"]),
                    dispatch_epoch=cast(int, row["dispatch_epoch"]),
                )
                await self._publisher.publish(message)
                await session.execute(
                    text(
                        "UPDATE analysis_outbox SET delivered_at = now() "
                        "WHERE event_id = :event_id AND delivered_at IS NULL"
                    ),
                    {"event_id": row["event_id"]},
                )
                dispatched += 1
        return dispatched
