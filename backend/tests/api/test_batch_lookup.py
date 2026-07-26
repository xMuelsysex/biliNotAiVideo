from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.api.test_analyses import BVID, _app, _token


@pytest.mark.asyncio
async def test_batch_returns_only_current_default_mapping_and_creates_no_work(
    engine,
) -> None:
    now = datetime.now(UTC)
    other = "BV1mK4y1C7Bz"
    async with engine.begin() as connection:
        for bvid, cid, checked_at in (
            (BVID, 501, now),
            (other, 502, now - timedelta(hours=24)),
        ):
            await connection.execute(
                text(
                    "INSERT INTO analysis_target "
                    "(bvid,cid,desired_analysis_version,write_generation) "
                    "VALUES (:bvid,:cid,'v1',1)"
                ),
                {"bvid": bvid, "cid": cid},
            )
            await connection.execute(
                text(
                    "INSERT INTO analysis_result "
                    "(bvid,cid,score,label,confidence,evidence_json,analysis_version," 
                    "analyzed_at,analysis_expires_at) VALUES "
                    "(:bvid,:cid,80,'high',0.9,'[]','v1',:now,:expiry)"
                ),
                {
                    "bvid": bvid,
                    "cid": cid,
                    "now": now,
                    "expiry": now + timedelta(days=1),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO video_metadata (bvid,default_cid,checked_at) "
                    "VALUES (:bvid,:cid,:checked_at)"
                ),
                {"bvid": bvid, "cid": cid, "checked_at": checked_at},
            )
    app = _app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        response = await client.post(
            "/api/v1/analyses/batch",
            json={"bvids": [BVID, other]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert [item["bvid"] for item in response.json()["items"]] == [BVID]
    async with engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM analysis_attempt"))
    assert count == 0


@pytest.mark.asyncio
async def test_batch_omits_results_from_an_old_analysis_version(engine) -> None:
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO analysis_target "
                "(bvid,cid,desired_analysis_version,write_generation) "
                "VALUES (:bvid,503,'v1',1)"
            ),
            {"bvid": BVID},
        )
        await connection.execute(
            text(
                "INSERT INTO analysis_result "
                "(bvid,cid,score,label,confidence,evidence_json,analysis_version,"
                "analyzed_at,analysis_expires_at) VALUES "
                "(:bvid,503,80,'high',0.9,'[]','v1',:now,:expiry)"
            ),
            {"bvid": BVID, "now": now, "expiry": now + timedelta(days=1)},
        )
        await connection.execute(
            text(
                "INSERT INTO video_metadata (bvid,default_cid,checked_at) "
                "VALUES (:bvid,503,:now)"
            ),
            {"bvid": BVID, "now": now},
        )
    app = _app(analysis_version="v2")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        response = await client.post(
            "/api/v1/analyses/batch",
            json={"bvids": [BVID]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_batch_rejects_duplicates_and_more_than_thirty() -> None:
    app = _app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = await _token(client)
        headers = {"Authorization": f"Bearer {token}"}
        duplicate = await client.post(
            "/api/v1/analyses/batch",
            json={"bvids": [BVID, BVID]},
            headers=headers,
        )
        too_many = await client.post(
            "/api/v1/analyses/batch",
            json={"bvids": [f"BV1Q54116{index:02d}" for index in range(31)]},
            headers=headers,
        )
    assert duplicate.status_code == 400
    assert too_many.status_code == 400
