from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

from redis.asyncio import Redis

_REFUND_SCRIPT = """
for i = 1, #KEYS do
    local current = tonumber(redis.call('GET', KEYS[i]) or '0')
    if current > 0 then
        redis.call('DECR', KEYS[i])
    end
end
return 1
"""

_FIXED_WINDOW_SCRIPT = """
for i = 1, #KEYS do
    local current = tonumber(redis.call('GET', KEYS[i]) or '0')
    local limit = tonumber(ARGV[(i - 1) * 2 + 1])
    if current >= limit then
        return {0, i, current}
    end
end
for i = 1, #KEYS do
    local value = redis.call('INCR', KEYS[i])
    local ttl = tonumber(ARGV[(i - 1) * 2 + 2])
    if value == 1 then
        redis.call('EXPIRE', KEYS[i], ttl)
    end
end
return {1, 0, 0}
"""


@dataclass(frozen=True, slots=True)
class RateLimit:
    name: str
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("rate limit must be positive")
        if self.window_seconds <= 0:
            raise ValueError("rate limit window must be positive")


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    exceeded: str | None = None


class RateLimiter:
    def __init__(self, redis: Redis, *, prefix: str = "bili-ai:rate") -> None:
        self._redis = redis
        self._prefix = prefix

    async def consume(
        self,
        subject: str,
        limits: tuple[RateLimit, ...],
    ) -> RateLimitDecision:
        if not subject:
            raise ValueError("rate-limit subject is required")
        if not limits:
            raise ValueError("at least one rate limit is required")
        keys = [f"{self._prefix}:{item.name}:{subject}" for item in limits]
        arguments = [str(value) for item in limits for value in (item.limit, item.window_seconds)]
        command = cast(
            Awaitable[list[int]],
            self._redis.eval(
                _FIXED_WINDOW_SCRIPT,
                len(keys),
                *(keys + arguments),
            ),
        )
        result = await command
        allowed = int(result[0]) == 1
        exceeded_index = int(result[1])
        return RateLimitDecision(
            allowed=allowed,
            exceeded=None if allowed else limits[exceeded_index - 1].name,
        )

    async def refund(self, subject: str, limits: tuple[RateLimit, ...]) -> None:
        keys = [f"{self._prefix}:{item.name}:{subject}" for item in limits]
        command = cast(
            Awaitable[int],
            self._redis.eval(_REFUND_SCRIPT, len(keys), *keys),
        )
        await command


class InstallationRateLimits:
    def __init__(
        self,
        limiter: RateLimiter,
        *,
        registration_burst: int,
        registration_daily: int,
        query_per_minute: int,
        analysis_hourly: int,
        analysis_daily: int,
    ) -> None:
        self._limiter = limiter
        self._registration = (
            RateLimit("registration:burst", registration_burst, 60),
            RateLimit("registration:daily", registration_daily, 86_400),
        )
        self._query = (RateLimit("query:minute", query_per_minute, 60),)
        self._analysis = (
            RateLimit("analysis:hour", analysis_hourly, 3_600),
            RateLimit("analysis:day", analysis_daily, 86_400),
        )

    async def consume_registration(self, ip_address: str) -> RateLimitDecision:
        return await self._limiter.consume(ip_address, self._registration)

    async def consume_query(self, token_id: str) -> RateLimitDecision:
        return await self._limiter.consume(token_id, self._query)

    async def consume_analysis_creation(self, token_id: str) -> RateLimitDecision:
        return await self._limiter.consume(token_id, self._analysis)

    async def refund_analysis_creation(self, token_id: str) -> None:
        await self._limiter.refund(token_id, self._analysis)
