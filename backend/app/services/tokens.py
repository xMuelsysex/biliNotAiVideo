import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    token_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedInstallation:
    token_id: UUID
    created_at: datetime


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(byte_length: int = 32) -> str:
    if byte_length < 32:
        raise ValueError("token byte length must be at least 32")
    return secrets.token_urlsafe(byte_length)


class TokenService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        token_byte_length: int = 32,
        last_used_write_interval: timedelta = timedelta(hours=1),
        idle_retention: timedelta = timedelta(days=90),
    ) -> None:
        if last_used_write_interval <= timedelta(0):
            raise ValueError("last_used_write_interval must be positive")
        if idle_retention <= timedelta(0):
            raise ValueError("idle_retention must be positive")
        self._session_factory = session_factory
        self._token_byte_length = token_byte_length
        self._last_used_write_interval = last_used_write_interval
        self._idle_retention = idle_retention

    async def create(self) -> IssuedToken:
        raw_token = issue_token(self._token_byte_length)
        token_id = uuid4()
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "INSERT INTO installation_token (token_id, token_hash) "
                        "VALUES (:token_id, :token_hash) RETURNING created_at"
                    ),
                    {"token_id": token_id, "token_hash": hash_token(raw_token)},
                )
            ).mappings().one()
        return IssuedToken(token=raw_token, token_id=token_id, created_at=row["created_at"])

    async def authenticate(self, raw_token: str) -> AuthenticatedInstallation | None:
        if not raw_token:
            return None
        now = datetime.now(UTC)
        write_before = now - self._last_used_write_interval
        active_after = now - self._idle_retention
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT token_id, created_at FROM installation_token "
                        "WHERE token_hash = :token_hash AND revoked_at IS NULL "
                        "AND COALESCE(last_used_at, created_at) > :active_after"
                    ),
                    {
                        "token_hash": hash_token(raw_token),
                        "active_after": active_after,
                    },
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            await session.execute(
                text(
                    "UPDATE installation_token SET last_used_at = :now "
                    "WHERE token_id = :token_id "
                    "AND (last_used_at IS NULL OR last_used_at <= :write_before)"
                ),
                {
                    "now": now,
                    "token_id": row["token_id"],
                    "write_before": write_before,
                },
            )
        return AuthenticatedInstallation(
            token_id=row["token_id"], created_at=row["created_at"]
        )

    async def rotate(self, current_token_id: UUID) -> IssuedToken | None:
        raw_token = issue_token(self._token_byte_length)
        new_token_id = uuid4()
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            revoked = await session.execute(
                text(
                    "UPDATE installation_token SET revoked_at = :now "
                    "WHERE token_id = :token_id AND revoked_at IS NULL "
                    "RETURNING token_id"
                ),
                {"now": now, "token_id": current_token_id},
            )
            if revoked.scalar_one_or_none() is None:
                return None
            row = (
                await session.execute(
                    text(
                        "INSERT INTO installation_token (token_id, token_hash) "
                        "VALUES (:token_id, :token_hash) RETURNING created_at"
                    ),
                    {"token_id": new_token_id, "token_hash": hash_token(raw_token)},
                )
            ).mappings().one()
        return IssuedToken(
            token=raw_token,
            token_id=new_token_id,
            created_at=row["created_at"],
        )
