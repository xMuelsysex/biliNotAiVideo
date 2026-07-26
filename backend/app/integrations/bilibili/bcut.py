import asyncio
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.integrations.bilibili.media import TranscriptSegment


class BCutError(RuntimeError):
    pass


class BCutTimeoutError(BCutError):
    pass


@dataclass(frozen=True, slots=True)
class BCutClient:
    client: httpx.AsyncClient
    poll_interval_seconds: float = 1.0
    timeout_seconds: float = 120.0

    async def transcribe_samples(
        self, samples: tuple[Path, ...]
    ) -> tuple[TranscriptSegment, ...]:
        segments: list[TranscriptSegment] = []
        for sample in samples:
            response = await self.client.post(
                "/bcut/upload",
                files={"file": (sample.name, sample.read_bytes(), "audio/wav")},
            )
            response.raise_for_status()
            task_id = str(response.json()["task_id"])
            segments.extend(await self._poll(task_id))
        return tuple(segments)

    async def _poll(self, task_id: str) -> tuple[TranscriptSegment, ...]:
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            response = await self.client.get(f"/bcut/tasks/{task_id}")
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == "completed":
                return tuple(
                    TranscriptSegment(
                        float(item["start"]),
                        float(item["end"]),
                        str(item["text"]),
                    )
                    for item in payload.get("segments", [])
                )
            if payload.get("status") == "failed":
                raise BCutError(str(payload.get("error", "transcription failed")))
            await asyncio.sleep(self.poll_interval_seconds)
        raise BCutTimeoutError(f"BCut task {task_id} timed out")
