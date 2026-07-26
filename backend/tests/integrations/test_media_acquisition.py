import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from app.integrations.bilibili.media import (
    MediaAcquirer,
    MediaCommandTimeoutError,
    WorkspaceLimitExceededError,
    run_command,
    task_workspace,
)


@pytest.mark.asyncio
async def test_subtitle_first_parses_json3(tmp_path: Path) -> None:
    async def runner(command: list[str]) -> None:
        output_index = command.index("-o") + 1
        output = Path(command[output_index]).with_name("subtitle.zh.json3")
        output.write_text(
            json.dumps(
                {
                    "events": [
                        {
                            "tStartMs": 1000,
                            "dDurationMs": 2000,
                            "segs": [{"utf8": "hello"}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    segments = await MediaAcquirer(runner).extract_subtitles("BV1Q541167Qg", tmp_path)
    assert segments[0].text == "hello"
    assert segments[0].start_seconds == 1
    assert segments[0].end_seconds == 3


@pytest.mark.asyncio
async def test_no_subtitle_and_sampling_commands_are_bounded(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    async def runner(command: list[str]) -> None:
        commands.append(command)
        if command[0] == "yt-dlp" and "--skip-download" in command:
            return
        output = Path(command[command.index("-o") + 1] if "-o" in command else command[-1])
        if "%" not in output.name:
            await asyncio.to_thread(output.touch)

    acquirer = MediaAcquirer(runner)
    assert await acquirer.extract_subtitles("BV1Q541167Qg", tmp_path, page=2) == ()
    samples = await acquirer.acquire_audio_samples(
        "BV1Q541167Qg", 300, tmp_path, page=2
    )
    await acquirer.sample_frames("BV1Q541167Qg", 300, tmp_path, 8, page=2)
    assert len(samples) == 3
    assert MediaAcquirer.sample_starts(300, 30) == (0, 135, 270)
    assert any("scale=-2:360" in part for command in commands for part in command)
    assert any("--max-filesize" in command for command in commands)
    assert any("-fs" in command for command in commands)
    video_urls = [
        part
        for command in commands
        for part in command
        if part.startswith("https://www.bilibili.com/video/")
    ]
    assert video_urls
    assert all(url.endswith("?p=2") for url in video_urls)
    frame_command = next(
        command for command in commands if command[0] == "ffmpeg" and "-frames:v" in command
    )
    frame_input = Path(frame_command[frame_command.index("-i") + 1])
    assert frame_input == tmp_path / "video.mp4"


@pytest.mark.asyncio
async def test_media_commands_enforce_timeout_and_workspace_size(tmp_path: Path) -> None:
    async def slow_runner(command: list[str]) -> None:
        del command
        await asyncio.sleep(1)

    with pytest.raises(MediaCommandTimeoutError, match="timed out") as timeout:
        await MediaAcquirer(
            slow_runner,
            command_timeout_seconds=0.001,
        ).extract_subtitles("BV1Q541167Qg", tmp_path)
    assert timeout.value.code == "media_command_timeout"

    async def oversized_runner(command: list[str]) -> None:
        output = Path(command[command.index("-o") + 1]).with_name("subtitle.zh.json3")
        output.write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceLimitExceededError, match="size limit") as oversized:
        await MediaAcquirer(
            oversized_runner,
            max_workspace_bytes=1,
        ).extract_subtitles("BV1Q541167Qg", tmp_path)
    assert oversized.value.code == "workspace_limit_exceeded"


@pytest.mark.asyncio
async def test_workspace_limit_cancels_running_command(tmp_path: Path) -> None:
    cancelled = asyncio.Event()

    async def growing_runner(command: list[str]) -> None:
        del command
        output = tmp_path / "growing.bin"
        try:
            while True:
                with output.open("ab") as stream:
                    stream.write(b"x" * 128)
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(WorkspaceLimitExceededError, match="size limit"):
        await MediaAcquirer(
            growing_runner,
            max_workspace_bytes=256,
            command_timeout_seconds=2,
        ).extract_subtitles("BV1Q541167Qg", tmp_path)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_real_media_tools_follow_bounded_sample_frames_chain(
    tmp_path: Path,
) -> None:
    await run_command([str(Path(sys.executable).with_name("yt-dlp")), "--version"])

    async def runner(command: list[str]) -> None:
        if command[0] == "yt-dlp":
            assert command[command.index("-f") + 1] == (
                "worstvideo[height<=360]/worst[height<=360]"
            )
            source = Path(command[command.index("-o") + 1])
            await run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x90:d=6",
                    "-c:v",
                    "mpeg4",
                    str(source),
                ]
            )
            return
        await run_command(command)

    frames = await MediaAcquirer(
        runner,
        command_timeout_seconds=30,
    ).sample_frames("BV1Q541167Qg", 6, tmp_path, count=6, page=2)
    assert len(frames) == 6
    files_exist = await asyncio.to_thread(
        lambda: all(frame.is_file() for frame in frames)
        and (tmp_path / "video.mp4").is_file()
    )
    assert files_exist


@pytest.mark.asyncio
async def test_run_command_terminates_process_group_on_cancel(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    task = asyncio.create_task(
        run_command(
            [
                sys.executable,
                "-c",
                (
                    "import os,pathlib,time,sys; "
                    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
                    "time.sleep(60)"
                ),
                str(pid_file),
            ]
        )
    )
    for _ in range(100):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert pid_file.exists()
    pid = int(pid_file.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_workspace_cleans_success_failure_and_cancellation(tmp_path: Path) -> None:
    paths: list[Path] = []
    async with task_workspace(str(tmp_path)) as workspace:
        paths.append(workspace)
        await asyncio.to_thread((workspace / "media").write_text, "x")
    assert not paths[0].exists()

    with pytest.raises(RuntimeError):
        async with task_workspace(str(tmp_path)) as workspace:
            paths.append(workspace)
            raise RuntimeError("failure")
    assert not paths[1].exists()

    async def cancelled() -> None:
        async with task_workspace(str(tmp_path)) as workspace:
            paths.append(workspace)
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cancelled()
    assert not paths[2].exists()
