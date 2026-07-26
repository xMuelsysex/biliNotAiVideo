from pathlib import Path

import httpx
import pytest

from app.integrations.bilibili.bcut import BCutClient, BCutTimeoutError


@pytest.mark.asyncio
async def test_bcut_upload_and_poll_returns_segments(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"audio")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-1"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "segments": [{"start": 0, "end": 1, "text": "speech"}],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        segments = await BCutClient(client).transcribe_samples((sample,))
    assert segments[0].text == "speech"


@pytest.mark.asyncio
async def test_bcut_timeout_is_typed(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"audio")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-2"})
        return httpx.Response(200, json={"status": "running"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://example.test"
    ) as client:
        with pytest.raises(BCutTimeoutError):
            await BCutClient(
                client,
                poll_interval_seconds=0.001,
                timeout_seconds=0.002,
            ).transcribe_samples((sample,))
