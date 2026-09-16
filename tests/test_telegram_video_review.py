from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.telegram_video_review_worker import (
    MAX_TELEGRAM_UPLOAD_BYTES,
    _load_upload_result,
    _video_bitrate_kbps,
    build_review_proxy,
)


def test_review_bitrate_targets_telegram_limit_for_25_minute_video():
    bitrate = _video_bitrate_kbps(1500.0, 44 * 1024 * 1024)
    assert 150 <= bitrate <= 260
    estimated_bytes = int(((bitrate + 48 + 12) * 1000 * 1500.0) / 8)
    assert estimated_bytes < MAX_TELEGRAM_UPLOAD_BYTES


def test_review_upload_result_requires_private_upload_identity(tmp_path: Path):
    path = tmp_path / "youtube-upload-result.json"
    path.write_text(
        json.dumps(
            {
                "status": "UPLOADED",
                "publication_id": 42,
                "video_id": 7,
                "youtube_url": "https://www.youtube.com/watch?v=private-review",
            }
        ),
        encoding="utf-8",
    )
    result = _load_upload_result(path)
    assert result["publication_id"] == 42


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "FAILED", "publication_id": 42, "youtube_url": "x"},
        {"status": "UPLOADED", "publication_id": 42},
        {"status": "UPLOADED", "youtube_url": "x"},
    ],
)
def test_review_upload_result_fails_closed(tmp_path: Path, payload: dict):
    path = tmp_path / "youtube-upload-result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError):
        _load_upload_result(path)


def test_review_proxy_rejects_truncated_full_duration_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "master.mp4"
    source.write_bytes(b"master")

    def fake_encode(_source, target, **_kwargs):
        target.write_bytes(b"proxy")

    durations = iter((1500.0, 1490.0))
    monkeypatch.setattr(
        "scripts.telegram_video_review_worker._encode_proxy", fake_encode
    )
    monkeypatch.setattr(
        "scripts.telegram_video_review_worker._duration_seconds",
        lambda _path: next(durations),
    )

    with pytest.raises(RuntimeError, match="duration does not match"):
        build_review_proxy(source, tmp_path / "review")
