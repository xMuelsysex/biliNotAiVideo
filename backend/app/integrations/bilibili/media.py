import asyncio
import json
import os
import shutil
import signal
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path


class MediaAcquisitionError(RuntimeError):
    code = "temporary_upstream_failure"


class MediaCommandTimeoutError(MediaAcquisitionError):
    code = "media_command_timeout"


class WorkspaceLimitExceededError(MediaAcquisitionError):
    code = "workspace_limit_exceeded"


class MediaCleanupError(RuntimeError):
    code = "cleanup_failed"


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str


CommandRunner = Callable[[list[str]], Awaitable[None]]


async def _stop_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
        return
    except TimeoutError:
        pass
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


async def run_command(command: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _, stderr = await process.communicate()
    except BaseException:
        await asyncio.shield(_stop_process_group(process))
        raise
    if process.returncode != 0:
        raise MediaAcquisitionError(stderr.decode("utf-8", errors="replace"))


async def _remove_workspace(path: Path) -> None:
    try:
        await asyncio.to_thread(shutil.rmtree, path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise MediaCleanupError(f"failed to remove media workspace: {path}") from error


@asynccontextmanager
async def task_workspace(root: str | None = None) -> AsyncIterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="bili-ai-", dir=root))
    try:
        yield path
    finally:
        await _remove_workspace(path)


class MediaAcquirer:
    def __init__(
        self,
        runner: CommandRunner = run_command,
        *,
        max_workspace_bytes: int = 268_435_456,
        command_timeout_seconds: float = 300,
    ) -> None:
        if max_workspace_bytes <= 0:
            raise ValueError("max_workspace_bytes must be positive")
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        self._runner = runner
        self._max_workspace_bytes = max_workspace_bytes
        self._command_timeout_seconds = command_timeout_seconds

    async def _workspace_size(self, workspace: Path) -> int:
        return await asyncio.to_thread(
            lambda: sum(
                path.stat().st_size
                for path in workspace.rglob("*")
                if path.is_file()
            )
        )

    async def _run(self, command: list[str], workspace: Path) -> None:
        task: asyncio.Future[None] = asyncio.ensure_future(self._runner(command))
        deadline = asyncio.get_running_loop().time() + self._command_timeout_seconds
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise MediaCommandTimeoutError("media command timed out")
                done, _ = await asyncio.wait(
                    {task},
                    timeout=min(0.25, remaining),
                )
                if await self._workspace_size(workspace) > self._max_workspace_bytes:
                    raise WorkspaceLimitExceededError(
                        "media workspace size limit exceeded"
                    )
                if task in done:
                    await task
                    return
        except BaseException:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    @staticmethod
    def _video_url(bvid: str, page: int) -> str:
        if page <= 0:
            raise ValueError("page must be positive")
        return f"https://www.bilibili.com/video/{bvid}?p={page}"

    async def extract_subtitles(
        self, bvid: str, workspace: Path, *, page: int = 1
    ) -> tuple[TranscriptSegment, ...]:
        output = workspace / "subtitle.%(ext)s"
        await self._run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                "zh-Hans,zh-CN,zh,en",
                "--sub-format",
                "json3",
                "-o",
                str(output),
                self._video_url(bvid, page),
            ],
            workspace,
        )
        files = await asyncio.to_thread(
            lambda: sorted(workspace.glob("subtitle*.json3"))
        )
        if not files:
            return ()
        return self.parse_json3(files[0])

    async def acquire_audio_samples(
        self,
        bvid: str,
        duration_seconds: int,
        workspace: Path,
        *,
        page: int = 1,
    ) -> tuple[Path, ...]:
        source = workspace / "audio.m4a"
        await self._run(
            [
                "yt-dlp",
                "--max-filesize",
                str(self._max_workspace_bytes),
                "-f",
                "bestaudio[abr<=64]/bestaudio",
                "-o",
                str(source),
                self._video_url(bvid, page),
            ],
            workspace,
        )
        starts = self.sample_starts(duration_seconds, 30)
        samples: list[Path] = []
        for index, start in enumerate(starts):
            output = workspace / f"audio-sample-{index}.wav"
            await self._run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(start),
                    "-t",
                    "30",
                    "-i",
                    str(source),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-fs",
                    str(self._max_workspace_bytes),
                    str(output),
                ],
                workspace,
            )
            samples.append(output)
        return tuple(samples)

    async def sample_frames(
        self,
        bvid: str,
        duration_seconds: int,
        workspace: Path,
        count: int = 8,
        *,
        page: int = 1,
    ) -> tuple[Path, ...]:
        if count < 6 or count > 12:
            raise ValueError("frame count must be between 6 and 12")
        source = workspace / "video.mp4"
        await self._run(
            [
                "yt-dlp",
                "--max-filesize",
                str(self._max_workspace_bytes),
                "-f",
                "worstvideo[height<=360]/worst[height<=360]",
                "-o",
                str(source),
                self._video_url(bvid, page),
            ],
            workspace,
        )
        output = workspace / "frame-%02d.jpg"
        interval = max(duration_seconds / count, 1)
        await self._run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-vf",
                f"fps=1/{interval:.3f},scale=-2:360",
                "-frames:v",
                str(count),
                "-fs",
                str(self._max_workspace_bytes),
                str(output),
            ],
            workspace,
        )
        return tuple(
            await asyncio.to_thread(lambda: sorted(workspace.glob("frame-*.jpg")))
        )

    @staticmethod
    def parse_json3(path: Path) -> tuple[TranscriptSegment, ...]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        segments: list[TranscriptSegment] = []
        for event in payload.get("events", []):
            texts = event.get("segs", [])
            text_value = "".join(str(item.get("utf8", "")) for item in texts).strip()
            if not text_value:
                continue
            start = float(event.get("tStartMs", 0)) / 1000
            duration = float(event.get("dDurationMs", 0)) / 1000
            segments.append(TranscriptSegment(start, start + duration, text_value))
        return tuple(segments)

    @staticmethod
    def sample_starts(duration_seconds: int, sample_seconds: int) -> tuple[int, ...]:
        if duration_seconds <= sample_seconds:
            return (0,)
        return (
            0,
            max((duration_seconds - sample_seconds) // 2, 0),
            max(duration_seconds - sample_seconds, 0),
        )
