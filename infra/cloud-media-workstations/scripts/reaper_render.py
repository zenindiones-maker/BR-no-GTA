#!/usr/bin/env python3
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import subprocess
import sys


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: reaper_render.py PROJECT.rpp OUTPUT", file=sys.stderr)
        return 2

    project = pathlib.Path(sys.argv[1]).resolve()
    output = pathlib.Path(sys.argv[2]).resolve()
    started = datetime.datetime.now(datetime.timezone.utc)

    receipt = {
        "schema": "MediaExecutionResult/v1",
        "status": "FAIL",
        "project": str(project),
        "input_project_sha256": None,
        "reaper_version": "7.82",
        "start_time": started.isoformat(),
        "end_time": None,
        "exit_code": None,
        "render_destination": str(output),
        "output_sha256": None,
        "duration": None,
        "audio": None,
        "failure_reason": None,
    }

    if not project.is_file():
        receipt["failure_reason"] = "PROJECT_MISSING"
        print(json.dumps(receipt, sort_keys=True))
        return 1

    receipt["input_project_sha256"] = sha256(project)

    proc = subprocess.run(
        ["/usr/local/bin/reaper", "-renderproject", str(project)],
        capture_output=True,
        text=True,
    )
    receipt["exit_code"] = proc.returncode
    receipt["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if proc.returncode != 0:
        receipt["failure_reason"] = "REAPER_RENDER_FAILED"
        print(json.dumps(receipt, sort_keys=True))
        return 1

    if not output.is_file():
        receipt["failure_reason"] = "OUTPUT_MISSING"
        print(json.dumps(receipt, sort_keys=True))
        return 1

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        receipt["failure_reason"] = "FFPROBE_FAILED"
        print(json.dumps(receipt, sort_keys=True))
        return 1

    media = json.loads(probe.stdout)
    receipt["output_sha256"] = sha256(output)
    receipt["duration"] = media.get("format", {}).get("duration")
    receipt["audio"] = next(
        (stream for stream in media.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    receipt["status"] = "PASS"
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
