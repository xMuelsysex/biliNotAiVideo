from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

FreshnessStatus = Literal["missing", "current", "stale"]


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    declaration_ttl: timedelta = timedelta(days=30)
    result_ttl: timedelta = timedelta(days=14)
    failed_cooldown: timedelta = timedelta(minutes=10)
    metadata_ttl: timedelta = timedelta(hours=24)

    @staticmethod
    def classify(expires_at: datetime | None, now: datetime) -> FreshnessStatus:
        if expires_at is None:
            return "missing"
        return "current" if expires_at > now else "stale"

    def declaration_status(
        self, checked_at: datetime | None, expires_at: datetime | None, now: datetime
    ) -> FreshnessStatus:
        if checked_at is None:
            return "missing"
        effective_expiry = expires_at or checked_at + self.declaration_ttl
        return self.classify(effective_expiry, now)

    def result_status(
        self, analyzed_at: datetime | None, expires_at: datetime | None, now: datetime
    ) -> FreshnessStatus:
        if analyzed_at is None:
            return "missing"
        effective_expiry = expires_at or analyzed_at + self.result_ttl
        return self.classify(effective_expiry, now)

    def metadata_is_current(self, checked_at: datetime, now: datetime) -> bool:
        return checked_at + self.metadata_ttl > now

    def cooldown_is_active(self, retry_after: datetime | None, now: datetime) -> bool:
        return retry_after is not None and retry_after > now
