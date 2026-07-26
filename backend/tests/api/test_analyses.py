import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings
from app.main import create_app

BACKEND_ROOT = Path(__file__).parents[2]
BVID = "BV1Q541167Qg"


def _database_url() -> str:
    url = os.getenv("BILI_AI_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("BILI_AI_TEST_DATABASE_URL is required")
    if not urlparse(url).path.removeprefix("/").endswith("_test"):
        pytest.fail("test database name must end with _test")
    return url


def _redis_url() -> str:
    url = os.getenv("BILI_AI_TEST_REDIS_URL")
    if url is None:
        pytest.skip("BILI_AI_TEST_REDIS_URL is required")
    return url


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = _database_url()
    command.upgrade(config, "head")
    yield


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_database_url())
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE analysis_outbox, analysis_result, video_declaration, "
                "analysis_attempt, analysis_target, installation_token CASCADE"
            )
        )
    redis = Redis.from_url(_redis_url())
    await redis.flushdb()
    await redis.aclose()
    try:
        yield engine
    finally:
        await engine.dispose()


def _app(**values: object):
    return create_app(
        Settings(
            _env_file=None,
            database_url=_database_url(),
            redis_url=_redis_url(),
            **values,
        )
    )


async def _token(client: AsyncClient) -> str:
    response = await client.post("/api/v1/installations")
    assert response.status_code == 201
    return response.json()["token"]


@pytest.mark.asyncio
async def test_missing_post_creates_once_and_reuses_active(engine: AsyncEngine) -> None:
    app = _app(analysis_hourly_limit=1, analysis_daily_limit=1)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        first = await client.post(
            "/api/v1/analyses", json={"bvid": BVID, "cid": 101}, headers=headers
        )
        second = await client.post(
            "/api/v1/analyses", json={"bvid": BVID, "cid": 101}, headers=headers
        )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["attempt_status"] == "queued"
    async with engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM analysis_attempt"))
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_posts_reuse_attempt_before_charging_quota(
    engine: AsyncEngine,
) -> None:
    app = _app(analysis_hourly_limit=1, analysis_daily_limit=1)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        responses = await asyncio.gather(
            *(
                client.post(
                    "/api/v1/analyses",
                    json={"bvid": BVID, "cid": 102},
                    headers=headers,
                )
                for _ in range(10)
            )
        )
    assert {response.status_code for response in responses} == {202}
    async with engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM analysis_attempt"))
    assert count == 1


@pytest.mark.asyncio
async def test_current_result_and_cooldown_bypass_creation_quota(
    engine: AsyncEngine,
) -> None:
    app = _app(analysis_hourly_limit=1, analysis_daily_limit=1)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post(
            "/api/v1/analyses", json={"bvid": BVID, "cid": 201}, headers=headers
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE analysis_attempt SET status='failed', retry_after=:retry "
                    "WHERE cid=201"
                ),
                {"retry": datetime.now(UTC) + timedelta(minutes=10)},
            )
        cooldown = await client.post(
            "/api/v1/analyses", json={"bvid": BVID, "cid": 201}, headers=headers
        )
        assert cooldown.status_code == 200
        assert cooldown.json()["attempt_status"] == "failed"

        now = datetime.now(UTC)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO analysis_target "
                    "(bvid,cid,desired_analysis_version,write_generation) "
                    "VALUES (:bvid,202,'v1',1)"
                ),
                {"bvid": BVID},
            )
            await connection.execute(
                text(
                    "INSERT INTO analysis_result "
                    "(bvid,cid,score,label,confidence,evidence_json,analysis_version," 
                    "analyzed_at,analysis_expires_at) "
                    "VALUES (:bvid,202,72,'medium',0.84,'[]','v1',:now,:expiry)"
                ),
                {"bvid": BVID, "now": now, "expiry": now + timedelta(days=1)},
            )
        current = await client.post(
            "/api/v1/analyses", json={"bvid": BVID, "cid": 202}, headers=headers
        )
    assert current.status_code == 200
    assert current.json()["result_status"] == "current"


@pytest.mark.asyncio
async def test_version_mismatch_marks_result_stale_and_replaces_old_attempt(
    engine: AsyncEngine,
) -> None:
    now = datetime.now(UTC)
    app = _app(analysis_version="v2")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO analysis_target "
                "(bvid,cid,desired_analysis_version,write_generation) "
                "VALUES (:bvid,203,'v1',1)"
            ),
            {"bvid": BVID},
        )
        old_attempt_id = await connection.scalar(text("SELECT gen_random_uuid()"))
        await connection.execute(
            text(
                "INSERT INTO analysis_attempt "
                "(attempt_id,bvid,cid,analysis_version,generation,status,dispatch_epoch) "
                "VALUES (:id,:bvid,203,'v1',1,'queued',0)"
            ),
            {"id": old_attempt_id, "bvid": BVID},
        )
        await connection.execute(
            text("UPDATE analysis_target SET owner_attempt_id=:id WHERE cid=203"),
            {"id": old_attempt_id},
        )
        await connection.execute(
            text(
                "INSERT INTO analysis_result "
                "(bvid,cid,score,label,confidence,evidence_json,analysis_version,"
                "analyzed_at,analysis_expires_at) "
                "VALUES (:bvid,203,72,'medium',0.84,'[]','v1',:now,:expiry)"
            ),
            {"bvid": BVID, "now": now, "expiry": now + timedelta(days=1)},
        )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        queried = await client.get(
            f"/api/v1/analyses/{BVID}?cid=203",
            headers=headers,
        )
        created = await client.post(
            "/api/v1/analyses",
            json={"bvid": BVID, "cid": 203},
            headers=headers,
        )
    assert queried.json()["result_status"] == "stale"
    assert created.status_code == 202
    assert created.json()["result_status"] == "stale"
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT analysis_version,status,error_code FROM analysis_attempt "
                    "WHERE cid=203 ORDER BY generation"
                )
            )
        ).mappings().all()
    assert [row["analysis_version"] for row in rows] == ["v1", "v2"]
    assert [row["status"] for row in rows] == ["failed", "queued"]
    assert rows[0]["error_code"] == "superseded"


@pytest.mark.asyncio
async def test_get_composes_stale_result_active_attempt_and_declaration(
    engine: AsyncEngine,
) -> None:
    app = _app()
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO analysis_target "
                "(bvid,cid,desired_analysis_version,write_generation) "
                "VALUES (:bvid,301,'v2',2)"
            ),
            {"bvid": BVID},
        )
        attempt_id = await connection.scalar(text("SELECT gen_random_uuid()"))
        await connection.execute(
            text(
                "INSERT INTO analysis_attempt "
                "(attempt_id,bvid,cid,analysis_version,generation,status,dispatch_epoch) "
                "VALUES (:id,:bvid,301,'v2',2,'queued',0)"
            ),
            {"id": attempt_id, "bvid": BVID},
        )
        await connection.execute(
            text("UPDATE analysis_target SET owner_attempt_id=:id WHERE cid=301"),
            {"id": attempt_id},
        )
        await connection.execute(
            text(
                "INSERT INTO analysis_result "
                "(bvid,cid,score,label,confidence,evidence_json,analysis_version," 
                "analyzed_at,analysis_expires_at) VALUES "
                "(:bvid,301,40,'light',0.7,'[]','v1',:old,:old)"
            ),
            {"bvid": BVID, "old": now - timedelta(days=1)},
        )
        await connection.execute(
            text(
                "INSERT INTO video_declaration "
                "(bvid,cid,state,source,checked_at,expires_at) "
                "VALUES (:bvid,301,'declared_ai','platform',:now,:expiry)"
            ),
            {"bvid": BVID, "now": now, "expiry": now + timedelta(days=1)},
        )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        response = await client.get(
            f"/api/v1/analyses/{BVID}?cid=301",
            headers={"Authorization": f"Bearer {token}"},
        )
    payload = response.json()
    assert payload["result_status"] == "stale"
    assert payload["attempt_status"] == "queued"
    assert payload["declaration"] == {
        "state": "declared_ai",
        "stale": False,
        "source": "platform",
    }
    assert payload["rule_version"] == "v1"
    assert payload["analyzed_at"] is not None


@pytest.mark.asyncio
async def test_failed_attempt_exposes_stable_public_error_code(engine: AsyncEngine) -> None:
    app = _app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post(
            "/api/v1/analyses", json={"bvid": BVID, "cid": 302}, headers=headers
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE analysis_attempt SET status='failed', "
                    "error_code='risk_control', retry_after=:retry WHERE cid=302"
                ),
                {"retry": datetime.now(UTC) + timedelta(minutes=10)},
            )
        response = await client.get(
            f"/api/v1/analyses/{BVID}?cid=302",
            headers=headers,
        )
    assert response.json()["error_code"] == "risk_control"


def test_openapi_exposes_snake_case_analysis_contract() -> None:
    schema = _app().openapi()
    properties = schema["components"]["schemas"]["AnalysisResponse"]["properties"]
    assert "analyzed_at" in properties
    assert "rule_version" in properties
    assert "error_code" in properties
    assert "analyzedAt" not in properties


@pytest.mark.asyncio
async def test_invalid_input_and_quota_use_typed_errors() -> None:
    app = _app(analysis_hourly_limit=1, analysis_daily_limit=1)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        invalid = await client.get("/api/v1/analyses/not-a-bv?cid=0", headers=headers)
        await client.post(
            "/api/v1/analyses", json={"bvid": BVID, "cid": 401}, headers=headers
        )
        quota = await client.post(
            "/api/v1/analyses", json={"bvid": BVID, "cid": 402}, headers=headers
        )
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_input"
    assert quota.status_code == 429
    assert quota.json()["detail"]["code"] == "analysis_quota_exhausted"
