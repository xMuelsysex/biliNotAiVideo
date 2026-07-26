from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.bilibili.client import BilibiliClient


@dataclass(frozen=True, slots=True)
class VideoPart:
    cid: int
    page: int
    title: str
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    bvid: str
    title: str
    description: str
    tags: tuple[str, ...]
    parts: tuple[VideoPart, ...]
    default_cid: int
    duration_seconds: int
    declaration_text: str | None


class MetadataService:
    def __init__(
        self,
        client: BilibiliClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._client = client
        self._session_factory = session_factory

    async def load(self, bvid: str, checked_at: datetime) -> VideoMetadata:
        view = (await self._client.get_json("/x/web-interface/view", {"bvid": bvid})).data
        tags_data = (await self._client.get_json("/x/tag/archive/tags", {"bvid": bvid})).data
        pages = view.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError("metadata contains no video parts")
        parts = tuple(
            VideoPart(
                cid=int(page["cid"]),
                page=int(page["page"]),
                title=str(page.get("part", "")),
                duration_seconds=int(page.get("duration", 0)),
            )
            for page in pages
            if isinstance(page, dict)
        )
        if not parts:
            raise ValueError("metadata contains no valid video parts")
        tags = tags_data.get("tags", tags_data)
        tag_items = tags if isinstance(tags, list) else []
        tag_names = tuple(
            str(item["tag_name"])
            for item in tag_items
            if isinstance(item, dict) and item.get("tag_name")
        )
        duration = view.get("duration", parts[0].duration_seconds)
        if not isinstance(duration, (int, str)):
            duration = parts[0].duration_seconds
        metadata = VideoMetadata(
            bvid=bvid,
            title=str(view.get("title", "")),
            description=str(view.get("desc", "")),
            tags=tag_names,
            parts=parts,
            default_cid=parts[0].cid,
            duration_seconds=int(duration),
            declaration_text=self._declaration_text(view),
        )
        await self._save_default_cid(metadata, checked_at)
        return metadata

    async def _save_default_cid(self, metadata: VideoMetadata, checked_at: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO video_metadata (bvid, default_cid, checked_at) "
                    "VALUES (:bvid, :cid, :checked_at) ON CONFLICT (bvid) DO UPDATE SET "
                    "default_cid=EXCLUDED.default_cid, checked_at=EXCLUDED.checked_at"
                ),
                {
                    "bvid": metadata.bvid,
                    "cid": metadata.default_cid,
                    "checked_at": checked_at,
                },
            )

    @staticmethod
    def _declaration_text(view: dict[str, object]) -> str | None:
        rights = view.get("rights")
        if isinstance(rights, dict) and rights.get("is_cooperation") == 1:
            return "platform cooperation declaration"
        desc = str(view.get("desc", ""))
        lowered = desc.lower()
        if any(marker in lowered for marker in ("ai生成", "ai 生成", "aigc", "人工智能生成")):
            return desc
        return None
