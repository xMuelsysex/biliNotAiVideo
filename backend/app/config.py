from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Bilibili AI Video Identification"
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_prefix="BILI_AI_",
        env_file=".env",
        extra="forbid",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
