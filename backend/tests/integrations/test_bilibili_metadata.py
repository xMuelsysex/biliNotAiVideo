from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.integrations.bilibili.client import BilibiliResponse
from app.integrations.bilibili.metadata import MetadataService


class FakeClient:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages

    async def get_json(self, path: str, params: dict[str, object]) -> BilibiliResponse:
        if "tags" in path:
            return BilibiliResponse(data={"tags": [{"tag_name": "AI"}]})
        return BilibiliResponse(
            data={
                "title": "title",
                "desc": "本视频使用 AI 生成",
                "duration": 120,
                "pages": self.pages,
            }
        )


@pytest.mark.asyncio
async def test_metadata_uses_first_current_part_and_refreshes_mapping(engine) -> None:
    service = MetadataService(
        FakeClient(
            [
                {"cid": 11, "page": 1, "part": "first", "duration": 60},
                {"cid": 12, "page": 2, "part": "second", "duration": 60},
            ]
        ),
        async_sessionmaker(engine, expire_on_commit=False),
    )
    metadata = await service.load("BV1Q541167Qg", datetime.now(UTC))
    assert metadata.default_cid == 11
    assert metadata.declaration_text is not None
    assert metadata.tags == ("AI",)

    service = MetadataService(
        FakeClient([{"cid": 12, "page": 1, "part": "second", "duration": 60}]),
        async_sessionmaker(engine, expire_on_commit=False),
    )
    await service.load("BV1Q541167Qg", datetime.now(UTC))
    async with engine.connect() as connection:
        cid = await connection.scalar(
            text("SELECT default_cid FROM video_metadata WHERE bvid='BV1Q541167Qg'")
        )
    assert cid == 12
