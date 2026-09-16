from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.telegram_video_review_worker import (
    MAX_TELEGRAM_UPLOAD_BYTES,
    _load_upload_result,
    _video_bitrate_kbps,
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
