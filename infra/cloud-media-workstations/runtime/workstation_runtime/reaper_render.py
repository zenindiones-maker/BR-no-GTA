from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Callable, Any


class RenderFailure(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_reaper_render(
    *,
    project: Path,
    expected_output: Path,
    reaper_binary: str,
    reaper_version: str,
    runner: Callable[[list[str]], tuple[int, str, str]],
    ffprobe: Callable[[Path], dict[str, Any]],
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    project = Path(project)
    expected_output = Path(expected_output)
    clock = now or (lambda: datetime.now(timezone.utc))
    if not project.is_file():
        raise RenderFailure("REAPER_PROJECT_MISSING")

    started = clock().astimezone(timezone.utc)
    input_hash = _sha256(project)
    exit_code, stdout, stderr = runner(
        [reaper_binary, "-renderproject", str(project)]
    )
    ended = clock().astimezone(timezone.utc)

    if exit_code != 0:
        raise RenderFailure(f"REAPER_RENDER_FAILED:EXIT_{exit_code}")
    if not expected_output.is_file():
        raise RenderFailure("REAPER_RENDER_FAILED:OUTPUT_MISSING")

    try:
        audio = ffprobe(expected_output)
    except Exception as exc:
        raise RenderFailure("REAPER_RENDER_FAILED:FFPROBE") from exc

    if not audio:
        raise RenderFailure("REAPER_RENDER_FAILED:INVALID_MEDIA")

    return {
        "schema": "MediaExecutionResult/v1",
        "status": "PASS",
        "project": str(project),
        "input_project_sha256": input_hash,
        "reaper_version": reaper_version,
        "start_time": started.isoformat(),
        "end_time": ended.isoformat(),
        "exit_code": exit_code,
        "render_destination": str(expected_output),
        "output_sha256": _sha256(expected_output),
        "duration": audio.get("duration"),
        "audio": {
            "codec_name": audio.get("codec_name"),
            "sample_rate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
        },
        "failure_reason": None,
    }
