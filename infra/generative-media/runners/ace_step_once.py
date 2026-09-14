from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def _request() -> dict:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    return payload


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_request(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("ACE-Step API returned a non-object response")
    return result


def _wait_health(base_url: str, process: subprocess.Popen, timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("ACE-Step loopback API exited during startup")
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=3) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError("ACE-Step loopback API health check timed out") from last_error


def _extract_task_id(response: dict) -> str:
    data = response.get("data")
    candidates = []
    if isinstance(data, dict):
        candidates.extend([data.get("task_id"), data.get("taskId"), data.get("id")])
    candidates.extend([response.get("task_id"), response.get("taskId")])
    for value in candidates:
        if isinstance(value, str) and value:
            return value
    raise RuntimeError("ACE-Step API did not return a task id")


def _extract_audio_path(response: dict) -> str | None:
    def walk(value):
        if isinstance(value, dict):
            for key in ("audio_path", "audioPath", "path", "file_path", "filePath"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate:
                    return candidate
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        return None

    return walk(response)


def main() -> None:
    payload = _request()
    prompt = payload.get("prompt")
    lyrics = payload.get("lyrics")
    if not (
        (isinstance(prompt, str) and prompt.strip())
        or (isinstance(lyrics, str) and lyrics.strip())
    ):
        raise ValueError("prompt or lyrics is required")

    output_root = Path(os.environ["BR_GENERATIVE_OUTPUT_DIR"])
    output_root.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = Path(os.environ["ACESTEP_CHECKPOINTS_DIR"])
    if not checkpoint_dir.is_dir():
        raise RuntimeError("Pinned ACE-Step checkpoint directory is unavailable")

    port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    server_env = dict(os.environ)
    server_env["ACESTEP_API_HOST"] = "127.0.0.1"
    server_env["ACESTEP_API_PORT"] = str(port)

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "acestep.api_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=server_env,
    )

    started = time.monotonic()
    try:
        _wait_health(base_url, process)
        request_payload = {
            "prompt": prompt or "",
            "lyrics": lyrics or "",
            "task_type": "text2music",
            "batch_size": 1,
            "audio_format": payload.get("audio_format", "wav"),
            "use_random_seed": payload.get("seed") is None,
        }
        if payload.get("seed") is not None:
            request_payload["seed"] = int(payload["seed"])
        if payload.get("audio_duration") is not None:
            request_payload["audio_duration"] = float(payload["audio_duration"])
        if payload.get("bpm") is not None:
            request_payload["bpm"] = int(payload["bpm"])
        if payload.get("key_scale") is not None:
            request_payload["key_scale"] = str(payload["key_scale"])
        if payload.get("time_signature") is not None:
            request_payload["time_signature"] = str(payload["time_signature"])

        released = _json_request(base_url + "/release_task", request_payload)
        task_id = _extract_task_id(released)

        deadline = time.monotonic() + float(payload.get("timeout_seconds", 1800))
        final = None
        while time.monotonic() < deadline:
            queried = _json_request(
                base_url + "/query_result",
                {"task_ids": [task_id]},
            )
            status_text = json.dumps(queried, sort_keys=True)
            if '"status": 2' in status_text or '"status": "2"' in status_text:
                raise RuntimeError("ACE-Step generation task failed")
            if '"status": 1' in status_text or '"status": "1"' in status_text:
                final = queried
                break
            time.sleep(2)

        if final is None:
            raise RuntimeError("ACE-Step generation task timed out")

        audio_path = _extract_audio_path(final)
        if not audio_path:
            raise RuntimeError("ACE-Step result did not expose an audio artifact path")
        artifact = Path(audio_path)
        if not artifact.is_absolute():
            artifact = Path.cwd() / artifact
        if not artifact.is_file():
            raise RuntimeError("ACE-Step returned audio artifact does not exist")

        suffix = artifact.suffix.lower()
        if suffix not in {".wav", ".flac", ".mp3", ".aac", ".opus", ".ogg"}:
            raise RuntimeError("ACE-Step returned unsupported audio artifact type")
        bounded_artifact = output_root / f"{task_id}{suffix}"
        shutil.copy2(artifact, bounded_artifact)

        result = {
            "path": str(bounded_artifact.resolve()),
            "backend": "ace_step",
            "seed": payload.get("seed"),
            "generation_config": {
                "task_type": "text2music",
                "audio_format": request_payload["audio_format"],
                "audio_duration": request_payload.get("audio_duration"),
                "bpm": request_payload.get("bpm"),
                "key_scale": request_payload.get("key_scale"),
                "time_signature": request_payload.get("time_signature"),
            },
            "elapsed_seconds": time.monotonic() - started,
            "warnings": [],
        }
        sys.stdout.write(json.dumps(result, sort_keys=True))
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
