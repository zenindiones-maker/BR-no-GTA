from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _request() -> dict:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    return payload


def main() -> None:
    payload = _request()
    source_image_path = Path(str(payload.get("source_image_path") or ""))
    prompt = payload.get("prompt")
    if not source_image_path.is_file():
        raise ValueError("source_image_path must reference a materialized image")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt is required")

    model_dir = Path(os.environ["BR_HUNYUAN_MODEL_DIR"])
    output_root = Path(os.environ["BR_GENERATIVE_OUTPUT_DIR"])
    if not model_dir.is_dir():
        raise RuntimeError("Pinned Hunyuan model directory is unavailable")
    output_root.mkdir(parents=True, exist_ok=True)

    seed = payload.get("seed")
    if seed is None:
        seed = 42
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    height = int(payload.get("height", 720))
    width = int(payload.get("width", 1280))
    video_length = int(payload.get("video_length", 129))
    infer_steps = int(payload.get("infer_steps", 50))
    if height <= 0 or width <= 0 or video_length <= 0 or infer_steps <= 0:
        raise ValueError("invalid Hunyuan generation dimensions/config")

    before = {p.resolve() for p in output_root.rglob("*.mp4")}
    started = time.monotonic()

    command = [
        sys.executable,
        "sample_image2video.py",
        "--model-base",
        str(model_dir),
        "--i2v-mode",
        "--i2v-image-path",
        str(source_image_path.resolve()),
        "--prompt",
        prompt,
        "--video-size",
        str(height),
        str(width),
        "--video-length",
        str(video_length),
        "--infer-steps",
        str(infer_steps),
        "--seed",
        str(seed),
        "--save-path",
        str(output_root),
        "--num-videos",
        "1",
    ]
    subprocess.run(command, check=True, stdout=sys.stderr, stderr=sys.stderr)

    after = {p.resolve() for p in output_root.rglob("*.mp4")}
    created = sorted(after - before, key=lambda p: str(p))
    if len(created) != 1:
        raise RuntimeError(
            f"Expected exactly one new Hunyuan MP4 artifact, found {len(created)}"
        )

    result = {
        "path": str(created[0]),
        "backend": "hunyuanvideo_i2v",
        "seed": seed,
        "generation_config": {
            "height": height,
            "width": width,
            "video_length": video_length,
            "infer_steps": infer_steps,
        },
        "elapsed_seconds": time.monotonic() - started,
        "warnings": [],
    }
    sys.stdout.write(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
