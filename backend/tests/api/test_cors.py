from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

APPROVED = "chrome-extension://abcdefghijklmnop"


def _app():
    return create_app(
        Settings(
            _env_file=None,
            allowed_extension_origins=[APPROVED],
        )
    )


async def test_approved_extension_origin_receives_cors_headers() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.get("/health", headers={"Origin": APPROVED})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == APPROVED


async def test_unlisted_extension_and_web_origins_receive_no_cors_permission() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        unlisted = await client.get(
            "/health", headers={"Origin": "chrome-extension://otherextension"}
        )
        web = await client.get("/health", headers={"Origin": "https://example.com"})

    assert "access-control-allow-origin" not in unlisted.headers
    assert "access-control-allow-origin" not in web.headers


async def test_preflight_allows_only_configured_origin_and_headers() -> None:
    app = _app()
    headers = {
        "Origin": APPROVED,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        approved = await client.options("/api/v1/installations/rotate", headers=headers)
        rejected = await client.options(
            "/api/v1/installations/rotate",
            headers={**headers, "Origin": "https://example.com"},
        )

    assert approved.status_code == 200
    assert approved.headers["access-control-allow-origin"] == APPROVED
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
