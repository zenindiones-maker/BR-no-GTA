from pathlib import Path

import pytest

from app.services.media_ingestion import IngestionStatus
from app.services.media_ingestion_result import (
    parse_ingestion_result,
)


def test_parse_download_ok() -> None:
    result = parse_ingestion_result(
        """
        {
          "status": "DOWNLOAD_OK",
          "source_url": "https://example.com/video",
          "output_path": "workspace/input/video.mp4",
          "reason": null
        }
        """
    )

    assert result.status is IngestionStatus.DOWNLOAD_OK
    assert result.source_url == "https://example.com/video"
    assert result.output_path == Path(
        "workspace/input/video.mp4"
    )
    assert result.reason is None


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (
            "DOWNLOAD_BLOCKED",
            "YOUTUBE_PLAYABILITY_LOGIN_REQUIRED",
        ),
        (
            "SOURCE_UNSUPPORTED",
            "SOURCE_UNSUPPORTED",
        ),
        (
            "SOURCE_UNAVAILABLE",
            "SOURCE_UNAVAILABLE",
        ),
    ],
)
def test_parse_non_success_domain_result(
    status: str,
    reason: str,
) -> None:
    result = parse_ingestion_result(
        f"""
        {{
          "status": "{status}",
          "source_url": "https://example.com/video",
          "output_path": null,
          "reason": "{reason}"
        }}
        """
    )

    assert result.status.value == status
    assert result.output_path is None
    assert result.reason == reason


def test_invalid_payload_raises() -> None:
    with pytest.raises(Exception):
        parse_ingestion_result(
            "not-json"
        )
