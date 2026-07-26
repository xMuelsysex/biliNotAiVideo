from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.__main__ import _load_materials
from app.db.repository import ClaimedAttempt
from app.domain.types import DeclarationState, TargetKey
from app.integrations.bilibili.client import BilibiliUnavailableError
from app.integrations.bilibili.media import MediaAcquisitionError, TranscriptSegment
from app.integrations.bilibili.metadata import VideoMetadata, VideoPart


class StubMetadataService:
    def __init__(self, metadata: VideoMetadata) -> None:
        self.metadata = metadata

    async def load(self, bvid: str, checked_at: datetime) -> VideoMetadata:
        assert bvid == self.metadata.bvid
        assert checked_at.tzinfo is not None
        return self.metadata


class RecordingRepository:
    def __init__(self) -> None:
        self.declarations = []

    async def save_declaration(self, target, declaration) -> None:
        self.declarations.append((target, declaration))


class RecordingMedia:
    def __init__(self, *, fail_subtitles: bool = False) -> None:
        self.fail_subtitles = fail_subtitles
        self.calls: list[tuple[object, ...]] = []

    async def extract_subtitles(self, bvid, workspace, *, page=1):
        self.calls.append(("subtitles", bvid, page))
        if self.fail_subtitles:
            raise MediaAcquisitionError("subtitle command failed")
        return (TranscriptSegment(0, 1, "text"),)

    async def acquire_audio_samples(self, bvid, duration, workspace, *, page=1):
        self.calls.append(("audio", bvid, duration, page))
        return ()

    async def sample_frames(self, bvid, duration, workspace, count=8, *, page=1):
        self.calls.append(("frames", bvid, duration, count, page))
        return ()


class NoopBCut:
    async def transcribe_samples(self, samples):
        raise AssertionError("subtitle hit must skip ASR")


def _claim(cid: int = 12) -> ClaimedAttempt:
    return ClaimedAttempt(
        attempt_id=uuid4(),
        target=TargetKey("BV1Q541167Qg", cid),
        analysis_version="v1",
        generation=1,
        dispatch_epoch=0,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def _metadata(declaration_text: str | None = "AI generated") -> VideoMetadata:
    return VideoMetadata(
        bvid="BV1Q541167Qg",
        title="multi-part",
        description=declaration_text or "ordinary",
        tags=(),
        parts=(
            VideoPart(11, 1, "first", 60),
            VideoPart(12, 2, "second", 30),
        ),
        default_cid=11,
        duration_seconds=90,
        declaration_text=declaration_text,
    )


@pytest.mark.asyncio
async def test_loader_binds_media_to_claimed_cid_part(tmp_path: Path) -> None:
    repository = RecordingRepository()
    media = RecordingMedia()
    materials = await _load_materials(
        _claim(),
        tmp_path,
        metadata_service=StubMetadataService(_metadata()),
        media=media,
        bcut=NoopBCut(),
        repository=repository,
        declaration_ttl=timedelta(days=30),
    )

    assert materials.transcript_source == "subtitle"
    assert media.calls == [
        ("subtitles", "BV1Q541167Qg", 2),
        ("frames", "BV1Q541167Qg", 30, 8, 2),
    ]
    target, declaration = repository.declarations[0]
    assert target.cid == 12
    assert declaration.state is DeclarationState.DECLARED_AI
    assert declaration.source == "description"


@pytest.mark.asyncio
async def test_declaration_persists_before_deep_media_failure(tmp_path: Path) -> None:
    repository = RecordingRepository()
    with pytest.raises(MediaAcquisitionError, match="subtitle command failed"):
        await _load_materials(
            _claim(),
            tmp_path,
            metadata_service=StubMetadataService(_metadata()),
            media=RecordingMedia(fail_subtitles=True),
            bcut=NoopBCut(),
            repository=repository,
            declaration_ttl=timedelta(days=30),
        )

    assert len(repository.declarations) == 1
    assert repository.declarations[0][1].state is DeclarationState.DECLARED_AI


@pytest.mark.asyncio
async def test_loader_rejects_cid_missing_from_current_parts(tmp_path: Path) -> None:
    repository = RecordingRepository()
    with pytest.raises(BilibiliUnavailableError, match="not a current part"):
        await _load_materials(
            _claim(99),
            tmp_path,
            metadata_service=StubMetadataService(_metadata(None)),
            media=RecordingMedia(),
            bcut=NoopBCut(),
            repository=repository,
            declaration_ttl=timedelta(days=30),
        )
    assert repository.declarations == []
