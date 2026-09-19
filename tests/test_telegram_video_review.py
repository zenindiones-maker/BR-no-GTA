from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.telegram_video_review_worker import _load_upload_result


def _ready_payload() -> dict:
    return {
        "status": "UPLOADED",
        "publication_id": 42,
        "video_id": 7,
        "youtube_url": "https://www.youtube.com/watch?v=private-review",
        "review_ready": True,
        "youtube_processing": {
            "status": "READY",
            "privacy_status": "private",
            "upload_status": "processed",
            "processing_status": "succeeded",
            "definition": "hd",
            "observations": 3,
        },
    }


def test_review_upload_result_requires_private_hd_ready_identity(tmp_path: Path):
    path = tmp_path / "youtube-upload-result.json"
    path.write_text(json.dumps(_ready_payload()), encoding="utf-8")

    result = _load_upload_result(path)

    assert result["publication_id"] == 42
    assert result["review_ready"] is True
    assert result["youtube_processing"]["definition"] == "hd"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "FAILED", "publication_id": 42, "youtube_url": "x"},
        {"status": "UPLOADED", "publication_id": 42},
        {"status": "UPLOADED", "youtube_url": "x"},
        {
            "status": "UPLOADED",
            "publication_id": 42,
            "youtube_url": "x",
            "review_ready": False,
            "youtube_processing": {},
        },
        {
            **_ready_payload(),
            "youtube_processing": {
                **_ready_payload()["youtube_processing"],
                "definition": "sd",
            },
        },
        {
            **_ready_payload(),
            "youtube_processing": {
                **_ready_payload()["youtube_processing"],
                "privacy_status": "unlisted",
            },
        },
    ],
)
def test_review_upload_result_fails_closed(tmp_path: Path, payload: dict):
    path = tmp_path / "youtube-upload-result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError):
        _load_upload_result(path)
