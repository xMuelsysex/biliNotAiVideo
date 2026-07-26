import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import TypedDict

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.analyses import router as analyses_router
from app.api.installations import router as installations_router
from app.config import Settings, get_settings
from app.db.analysis_queries import AnalysisQueryRepository
from app.db.repository import AnalysisRepository
from app.logging import configure_logging
from app.services.freshness import FreshnessPolicy
from app.services.rate_limits import InstallationRateLimits, RateLimiter
from app.services.tokens import TokenService

logger = logging.getLogger(__name__)


class HealthResponse(TypedDict):
    status: str


class ReadyResponse(TypedDict):
    status: str
    database: str
    redis: str


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    resolved_settings = settings or get_settings()
    engine = create_async_engine(resolved_settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(resolved_settings.redis_url, decode_responses=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await redis.aclose()
        await engine.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.token_service = TokenService(
        session_factory,
        token_byte_length=resolved_settings.token_byte_length,
        last_used_write_interval=timedelta(
            minutes=resolved_settings.token_last_used_write_minutes
        ),
        idle_retention=timedelta(days=resolved_settings.token_idle_retention_days),
    )
    application.state.analysis_queries = AnalysisQueryRepository(session_factory)
    application.state.analysis_repository = AnalysisRepository(session_factory)
    application.state.freshness_policy = FreshnessPolicy(
        declaration_ttl=timedelta(days=resolved_settings.declaration_ttl_days),
        result_ttl=timedelta(days=resolved_settings.analysis_ttl_days),
        failed_cooldown=timedelta(
            minutes=resolved_settings.failed_attempt_cooldown_minutes
        ),
        metadata_ttl=timedelta(hours=resolved_settings.metadata_ttl_hours),
    )
    application.state.analysis_version = resolved_settings.analysis_version
    application.state.rate_limits = InstallationRateLimits(
        RateLimiter(redis),
        registration_burst=resolved_settings.registration_ip_burst_limit,
        registration_daily=resolved_settings.registration_ip_daily_limit,
        query_per_minute=resolved_settings.query_per_minute_limit,
        analysis_hourly=resolved_settings.analysis_hourly_limit,
        analysis_daily=resolved_settings.analysis_daily_limit,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_extension_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.include_router(installations_router)
    application.include_router(analyses_router)

    @application.middleware("http")
    async def request_logging(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request failed",
                extra={
                    "request_id": request_id,
                    "stage": request.url.path,
                    "duration_ms": duration_ms,
                    "error_code": "unhandled_exception",
                },
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["x-request-id"] = request_id
        logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "stage": request.url.path,
                "duration_ms": duration_ms,
            },
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_input(_: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": {"code": "invalid_input"}},
        )

    @application.get("/health", tags=["health"])
    async def health() -> HealthResponse:
        return {"status": "ok"}

    @application.get("/ready", tags=["health"], response_model=None)
    async def ready() -> ReadyResponse | JSONResponse:
        database_status = "ok"
        redis_status = "ok"
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            database_status = "unavailable"
        try:
            if await redis.ping() is not True:
                redis_status = "unavailable"
        except Exception:
            redis_status = "unavailable"
        payload: ReadyResponse = {
            "status": "ok" if database_status == "ok" and redis_status == "ok" else "degraded",
            "database": database_status,
            "redis": redis_status,
        }
        if payload["status"] != "ok":
            return JSONResponse(status_code=503, content=payload)
        return payload

    return application


app = create_app()
