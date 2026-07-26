from datetime import UTC, datetime, timedelta

from app.services.freshness import FreshnessPolicy


def test_expiry_instant_is_stale() -> None:
    now = datetime.now(UTC)
    policy = FreshnessPolicy()

    assert policy.result_status(now - timedelta(days=1), now, now) == "stale"
    assert policy.declaration_status(now - timedelta(days=1), now, now) == "stale"
    assert not policy.metadata_is_current(now - timedelta(hours=24), now)
    assert not policy.cooldown_is_active(now, now)


def test_values_after_boundary_are_current() -> None:
    now = datetime.now(UTC)
    policy = FreshnessPolicy()

    assert policy.result_status(now, now + timedelta(microseconds=1), now) == "current"
    assert policy.declaration_status(now, now + timedelta(seconds=1), now) == "current"
    assert policy.metadata_is_current(now - timedelta(hours=23), now)
    assert policy.cooldown_is_active(now + timedelta(seconds=1), now)
