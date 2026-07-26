import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.services.rate_limits import InstallationRateLimits, RateLimiter


def _redis_url() -> str:
    url = os.getenv("BILI_AI_TEST_REDIS_URL")
    if url is None:
        pytest.skip("BILI_AI_TEST_REDIS_URL is required for Redis tests")
    return url


@pytest.mark.asyncio
async def test_registration_checks_burst_and_daily_windows_atomically() -> None:
    redis = Redis.from_url(_redis_url(), decode_responses=True)
    prefix = f"test-rate:{uuid4()}"
    limits = InstallationRateLimits(
        RateLimiter(redis, prefix=prefix),
        registration_burst=2,
        registration_daily=3,
        query_per_minute=60,
        analysis_hourly=5,
        analysis_daily=20,
    )
    try:
        assert (await limits.consume_registration("203.0.113.10")).allowed
        assert (await limits.consume_registration("203.0.113.10")).allowed
        denied = await limits.consume_registration("203.0.113.10")
        assert not denied.allowed
        assert denied.exceeded == "registration:burst"
        daily_value = await redis.get(f"{prefix}:registration:daily:203.0.113.10")
        assert daily_value == "2"
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_analysis_hourly_denial_does_not_increment_daily_window() -> None:
    redis = Redis.from_url(_redis_url(), decode_responses=True)
    prefix = f"test-rate:{uuid4()}"
    limits = InstallationRateLimits(
        RateLimiter(redis, prefix=prefix),
        registration_burst=3,
        registration_daily=10,
        query_per_minute=60,
        analysis_hourly=2,
        analysis_daily=20,
    )
    try:
        assert (await limits.consume_analysis_creation("token-1")).allowed
        assert (await limits.consume_analysis_creation("token-1")).allowed
        denied = await limits.consume_analysis_creation("token-1")
        assert not denied.allowed
        assert denied.exceeded == "analysis:hour"
        daily_value = await redis.get(f"{prefix}:analysis:day:token-1")
        assert daily_value == "2"
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_query_and_daily_analysis_limits_are_independent() -> None:
    redis = Redis.from_url(_redis_url(), decode_responses=True)
    prefix = f"test-rate:{uuid4()}"
    limits = InstallationRateLimits(
        RateLimiter(redis, prefix=prefix),
        registration_burst=3,
        registration_daily=10,
        query_per_minute=1,
        analysis_hourly=10,
        analysis_daily=2,
    )
    try:
        assert (await limits.consume_query("token-2")).allowed
        assert not (await limits.consume_query("token-2")).allowed
        assert (await limits.consume_analysis_creation("token-2")).allowed
        assert (await limits.consume_analysis_creation("token-2")).allowed
        denied = await limits.consume_analysis_creation("token-2")
        assert not denied.allowed
        assert denied.exceeded == "analysis:day"
    finally:
        await redis.aclose()
