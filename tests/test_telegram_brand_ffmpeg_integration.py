from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from app.workers.brand_asset_worker import apply


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe required")
def test_real_ffmpeg_applies_intro_and_watermark_and_preserves_audiovisual_qa(tmp_path: Path):
    runtime_root = tmp_path / "runtime"
    output_root = tmp_path / "output"
    execution_id = "telegram-brand-proof"
    render_job_id = 41
    video_id = 51
    brand_folder = runtime_root / "branding" / execution_id / str(render_job_id)
    render_folder = output_root / execution_id / str(render_job_id)
    brand_folder.mkdir(parents=True)
    render_folder.mkdir(parents=True)

    base = render_folder / f"{video_id}.mp4"
    intro = tmp_path / "intro.mp4"
    watermark = tmp_path / "watermark.png"

    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=3",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", str(base),
        ]
    )
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=320x180:r=10:d=1",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", str(intro),
        ]
    )
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=white:s=32x32",
            "-frames:v", "1", str(watermark),
        ]
    )

    job = {
        "render_job_id": render_job_id,
        "video_id": video_id,
        "content_item_id": 61,
        "script_id": 71,
        "idea_id": 81,
        "execution_id": execution_id,
        "brain_decision_id": "telegram-brand-proof-decision",
        "authorized_action": "EXECUTION",
        "estimated_duration_seconds": 3.0,
        "render": {"resolution": "320x180", "fps": 10},
    }
    state = {
        "assets": [
            {
                "asset_id": 1,
                "asset_type": "intro",
                "telegram_file_unique_id": "proof-intro",
                "media_path": str(intro),
                "mime_type": "video/mp4",
                "duration_seconds": 1.0,
                "has_audio": True,
                "sha256": "a" * 64,
                "size_bytes": intro.stat().st_size,
            },
            {
                "asset_id": 2,
                "asset_type": "watermark",
                "telegram_file_unique_id": "proof-watermark",
                "media_path": str(watermark),
                "mime_type": "image/png",
                "duration_seconds": None,
                "has_audio": False,
                "sha256": "b" * 64,
                "size_bytes": watermark.stat().st_size,
            },
        ]
    }
    (brand_folder / "brand-state.json").write_text(json.dumps(state), encoding="utf-8")
    (brand_folder / "brand-assets.json").write_text(
        json.dumps({"status": "PASS", "materialization_boundary": "cloud-only", "assets": []}),
        encoding="utf-8",
    )
    (render_folder / "render-qa.json").write_text(
        json.dumps({"status": "PASS"}),
        encoding="utf-8",
    )

    result = apply(job, runtime_root, output_root)

    assert result == base
    assert base.is_file() and base.stat().st_size > 0
    qa = json.loads((render_folder / "render-qa.json").read_text(encoding="utf-8"))
    manifest = json.loads((render_folder / "render-manifest.json").read_text(encoding="utf-8"))
    probe = json.loads((render_folder / "video-probe.json").read_text(encoding="utf-8"))

    assert qa["status"] == "PASS"
    assert qa["stage"] == "brand-complete"
    assert qa["checks"]["video_stream"] is True
    assert qa["checks"]["audio_stream"] is True
    assert qa["checks"]["full_decode"] is True
    assert qa["checks"]["brand_assets_applied"] is True
    assert manifest["qa_status"] == "PASS"
    assert manifest["brand_asset_ids"] == [1, 2]
    assert manifest["brand_asset_types"] == ["intro", "watermark"]
    assert manifest["brand_composition"] == "telegram-cloud-ffmpeg"
    assert probe["brand_assets"] == [
        {"asset_id": 1, "asset_type": "intro", "telegram_file_unique_id": "proof-intro", "sha256": "a" * 64},
        {"asset_id": 2, "asset_type": "watermark", "telegram_file_unique_id": "proof-watermark", "sha256": "b" * 64},
    ]
