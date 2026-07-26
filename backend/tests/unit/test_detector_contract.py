import json

import httpx
import pytest

from app.detectors.openai_compatible import DetectorRequestError, OpenAICompatibleDetector
from app.domain.types import DetectorKind


@pytest.mark.asyncio
async def test_detector_requires_strict_finite_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{\"score\": NaN}"}}]},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://ai.test"
    ) as client:
        with pytest.raises(DetectorRequestError):
            await OpenAICompatibleDetector(client, model="test").detect_text("prompt", 1.0)


@pytest.mark.asyncio
async def test_detector_uses_local_material_factor() -> None:
    payload = {
        "kind": "text",
        "score": 0.8,
        "confidence": 0.9,
        "material_factor": 1.0,
        "evidence": [{"description": "specific production evidence", "timestamp_seconds": 3}],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://ai.test"
    ) as client:
        output = await OpenAICompatibleDetector(client, model="test").detect_text(
            "prompt", 0.7
        )
    assert output.kind is DetectorKind.TEXT
    assert output.material_factor == 0.7
