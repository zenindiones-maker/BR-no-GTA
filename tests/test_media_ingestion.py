from pathlib import Path

from app.services.media_ingestion import (
    IngestionResult,
    IngestionStatus,
)


def test_download_ok_is_successful() -> None:
    result = IngestionResult(
        status=IngestionStatus.DOWNLOAD_OK,
        source_url="https://example.com/video.mp4",
        output_path=Path("workspace/input/video.mp4"),
    )

    assert result.succeeded is True


def test_download_blocked_is_not_successful() -> None:
    result = IngestionResult(
        status=IngestionStatus.DOWNLOAD_BLOCKED,
        source_url="https://www.youtube.com/watch?v=test",
        reason="YOUTUBE_PLAYABILITY_LOGIN_REQUIRED",
    )

    assert result.succeeded is False


def test_source_unsupported_is_not_successful() -> None:
    result = IngestionResult(
        status=IngestionStatus.SOURCE_UNSUPPORTED,
        source_url="https://example.com/unknown",
        reason="SOURCE_UNSUPPORTED",
    )

    assert result.succeeded is False


def test_source_unavailable_is_not_successful() -> None:
    result = IngestionResult(
        status=IngestionStatus.SOURCE_UNAVAILABLE,
        source_url="https://example.com/missing.mp4",
        reason="SOURCE_UNAVAILABLE",
    )

    assert result.succeeded is False
