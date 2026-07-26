from functools import lru_cache
from typing import Annotated

from pydantic import Field, PositiveInt, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Bilibili AI Video Identification"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://postgres@localhost:5432/bili_ai"
    redis_url: str = "redis://localhost:6379/0"
    token_byte_length: Annotated[int, Field(ge=32)] = 32
    token_last_used_write_minutes: PositiveInt = 60
    token_idle_retention_days: PositiveInt = 90
    registration_ip_burst_limit: PositiveInt = 3
    registration_ip_daily_limit: PositiveInt = 10
    query_per_minute_limit: PositiveInt = 60
    analysis_hourly_limit: PositiveInt = 5
    analysis_daily_limit: PositiveInt = 20
    analysis_version: str = "v1"
    declaration_ttl_days: PositiveInt = 30
    analysis_ttl_days: PositiveInt = 14
    failed_attempt_cooldown_minutes: PositiveInt = 10
    metadata_ttl_hours: PositiveInt = 24
    bilibili_cookie: str | None = None
    bilibili_request_timeout_seconds: PositiveInt = 20
    bilibili_max_retries: int = 2
    media_temp_root: str | None = None
    media_workspace_max_bytes: PositiveInt = 268_435_456
    media_command_timeout_seconds: PositiveInt = 300
    analysis_task_timeout_seconds: PositiveInt = 900
    bcut_api_base: str | None = None
    bcut_poll_timeout_seconds: PositiveInt = 120
    ai_api_base: str = "https://api.openai.com/v1"
    ai_api_key: str | None = None
    ai_model: str = "gpt-4o-mini"
    ai_request_timeout_seconds: PositiveInt = 60
    ai_max_evidence_items: PositiveInt = 8
    allowed_extension_origins: list[str] = []

    @field_validator("allowed_extension_origins")
    @classmethod
    def validate_extension_origins(cls, origins: list[str]) -> list[str]:
        if any(
            not origin.startswith("chrome-extension://")
            or origin.count("://") != 1
            or "/" in origin.removeprefix("chrome-extension://")
            or not origin.removeprefix("chrome-extension://")
            for origin in origins
        ):
            raise ValueError("allowed origins must be exact chrome-extension origins")
        if len(origins) != len(set(origins)):
            raise ValueError("allowed origins must be unique")
        return origins

    model_config = SettingsConfigDict(
        env_prefix="BILI_AI_",
        env_file=".env",
        extra="forbid",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
