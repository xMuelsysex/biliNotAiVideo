from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_health_returns_ok() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_application_openapi_is_importable() -> None:
    schema = create_app().openapi()

    assert schema["info"]["title"] == "Bilibili AI Video Identification"
    assert "/health" in schema["paths"]
