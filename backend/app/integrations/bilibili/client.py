import asyncio
from dataclasses import dataclass

import httpx


class BilibiliError(RuntimeError):
    code = "bilibili_error"


class BilibiliRiskControlError(BilibiliError):
    code = "risk_control"


class BilibiliUnavailableError(BilibiliError):
    code = "video_unavailable"


class BilibiliTemporaryError(BilibiliError):
    code = "temporary_upstream_failure"


@dataclass(frozen=True, slots=True)
class BilibiliResponse:
    data: dict[str, object]


class BilibiliClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_retries: int = 2,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        self._client = client
        self._max_retries = max_retries

    @staticmethod
    def headers(cookie: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/131.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
        }
        if cookie:
            headers["Cookie"] = cookie
        return headers

    async def get_json(self, path: str, params: dict[str, str | int]) -> BilibiliResponse:
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                if attempt == self._max_retries:
                    raise BilibiliTemporaryError(str(error)) from error
                await asyncio.sleep(0.05 * (2**attempt))
                continue
            code = int(payload.get("code", -1))
            if code == 0 and isinstance(payload.get("data"), dict):
                return BilibiliResponse(data=payload["data"])
            if code in {-352, -412}:
                raise BilibiliRiskControlError(str(payload.get("message", "risk control")))
            if code in {-404, 62002, 62004, 62012}:
                raise BilibiliUnavailableError(str(payload.get("message", "unavailable")))
            raise BilibiliTemporaryError(str(payload.get("message", f"code {code}")))
        raise AssertionError("unreachable")
