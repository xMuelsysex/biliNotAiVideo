from typing import TypedDict

from fastapi import FastAPI

from app.config import get_settings


class HealthResponse(TypedDict):
    status: str


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version="0.1.0")

    @application.get("/health", tags=["health"])
    async def health() -> HealthResponse:
        return {"status": "ok"}

    return application


app = create_app()
