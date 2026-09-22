from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.telegram_render_review_worker import (
    READY_FOR_HUMAN_REVIEW,
    deliver_render_review,
)


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_successful_delivery_persists_ready_for_human_review() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "output"
        folder = root / "execution-canary" / "910001"
        folder.mkdir(parents=True)
        source = folder / "910001.mp4"
        source.write_bytes(b"real-render-placeholder-for-transport-unit-test")
        _write(
            folder / "render-job.json",
            {
                "render_job_id": 910001,
                "video_id": 910001,
                "execution_id": "run001-e2e-canary-v1",
                "brand_assets": [
                    {"asset_id": 1, "asset_type": "intro"},
                    {"asset_id": 2, "asset_type": "watermark"},
                ],
            },
        )
        _write(
            folder / "render-qa.json",
            {
                "status": "PASS",
                "duration_seconds": 56.0,
                "branding": {
                    "intro_duration_seconds": 11.0,
                    "watermark_start_seconds": 11.0,
                },
            },
        )

        with patch(
            "scripts.telegram_render_review_worker._send_document",
            return_value={
                "message_id": 77,
                "document": {"file_id": "file-1", "file_unique_id": "unique-1"},
            },
        ), patch(
            "scripts.telegram_render_review_worker._sha256",
            return_value="0" * 64,
        ):
            result = deliver_render_review(
                artifact_root=root,
                token="test-token",
                review_chat_id="123456",
                run_id="999",
                explicit_human_request=True,
                human_request_ref="telegram-turn:test-review-request",
            )

        assert result["status"] == "DELIVERED"
        assert result["telegram_review_delivery"] == "PASS"
        assert result["telegram_message_id"] == 77
        assert result["human_review_state"] == READY_FOR_HUMAN_REVIEW
        assert (
            result["boundary"]
            == "EXPLICIT_HUMAN_REQUEST_REVIEW_ONLY_NO_PUBLICATION_AUTHORITY"
        )
        persisted = json.loads((folder / "telegram-review.json").read_text(encoding="utf-8"))
        assert persisted["human_review_state"] == READY_FOR_HUMAN_REVIEW
        assert persisted["telegram_message_id"] == 77
