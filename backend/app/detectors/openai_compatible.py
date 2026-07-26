import asyncio
import base64
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.domain.errors import InvalidDetectorOutput
from app.domain.types import DetectorKind, DetectorOutput


class DetectorRequestError(RuntimeError):
    pass


class OpenAICompatibleDetector:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        max_evidence_items: int = 8,
    ) -> None:
        self._client = client
        self._model = model
        self._max_evidence_items = max_evidence_items

    async def detect_text(
        self, prompt: str, material_factor: float
    ) -> DetectorOutput:
        return await self._request(
            DetectorKind.TEXT,
            [{"type": "text", "text": prompt}],
            material_factor,
        )

    async def detect_visual(
        self, prompt: str, frames: tuple[Path, ...], material_factor: float
    ) -> DetectorOutput:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        for frame in frames:
            frame_bytes = await asyncio.to_thread(frame.read_bytes)
            encoded = base64.b64encode(frame_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )
        return await self._request(DetectorKind.VISUAL, content, material_factor)

    async def _request(
        self,
        kind: DetectorKind,
        content: list[dict[str, object]],
        material_factor: float,
    ) -> DetectorOutput:
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": content}],
                },
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            detector = DetectorOutput.model_validate_json(raw)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValidationError) as error:
            raise DetectorRequestError(str(error)) from error
        if detector.kind != kind:
            raise InvalidDetectorOutput(
                reason=f"expected {kind.value} detector output",
                detector_kind=detector.kind.value,
            )
        if detector.material_factor != material_factor:
            detector = detector.model_copy(update={"material_factor": material_factor})
        if len(detector.evidence) > self._max_evidence_items:
            raise InvalidDetectorOutput(
                reason="too many evidence items",
                detector_kind=kind.value,
            )
        return detector
