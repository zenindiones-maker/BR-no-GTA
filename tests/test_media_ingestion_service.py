from pathlib import Path

from app.services.media_ingestion import (
    IngestionResult,
    IngestionStatus,
)
from app.services.media_ingestion_service import (
    MediaIngestionService,
)


class FakeMediaIngestionProvider:
    def __init__(self, result: IngestionResult) -> None:
        self.result = result
        self.calls: list[tuple[str, Path]] = []

    def ingest(
        self,
        source_url: str,
        output_path: Path,
    ) -> IngestionResult:
        self.calls.append((source_url, output_path))
        return self.result


def test_service_delegates_ingestion_to_provider() -> None:
    result = IngestionResult(
        status=IngestionStatus.DOWNLOAD_OK,
        source_url="https://example.com/video",
        output_path=Path("workspace/input/video.mp4"),
    )

    provider = FakeMediaIngestionProvider(result)
    service = MediaIngestionService(provider)

    returned = service.ingest(
        source_url="https://example.com/video",
        output_path=Path("workspace/input/video.mp4"),
    )

    assert returned is result
    assert provider.calls == [
        (
            "https://example.com/video",
            Path("workspace/input/video.mp4"),
        )
    ]


def test_service_adds_mp4_suffix_when_output_has_no_suffix() -> None:
    result = IngestionResult(
        status=IngestionStatus.DOWNLOAD_OK,
        source_url="https://example.com/video",
        output_path=Path("workspace/input/video.mp4"),
    )

    provider = FakeMediaIngestionProvider(result)
    service = MediaIngestionService(provider)

    service.ingest(
        source_url="https://example.com/video",
        output_path=Path("workspace/input/video"),
    )

    assert provider.calls == [
        (
            "https://example.com/video",
            Path("workspace/input/video.mp4"),
        )
    ]


def test_empty_source_url_is_rejected_without_provider_call() -> None:
    provider = FakeMediaIngestionProvider(
        IngestionResult(
            status=IngestionStatus.DOWNLOAD_OK,
            source_url="",
        )
    )
    service = MediaIngestionService(provider)

    result = service.ingest(
        source_url="   ",
        output_path=Path("workspace/input/video.mp4"),
    )

    assert result.status is IngestionStatus.SOURCE_UNSUPPORTED
    assert result.reason == "SOURCE_URL_EMPTY"
    assert provider.calls == []


def test_blocked_ingestion_is_returned_unchanged() -> None:
    result = IngestionResult(
        status=IngestionStatus.DOWNLOAD_BLOCKED,
        source_url="https://www.youtube.com/watch?v=test",
        reason="YOUTUBE_PLAYABILITY_LOGIN_REQUIRED",
    )

    provider = FakeMediaIngestionProvider(result)
    service = MediaIngestionService(provider)

    returned = service.ingest(
        source_url=result.source_url,
        output_path=Path("workspace/input/video.mp4"),
    )

    assert returned.status is IngestionStatus.DOWNLOAD_BLOCKED
    assert returned.reason == "YOUTUBE_PLAYABILITY_LOGIN_REQUIRED"
    assert returned.succeeded is False
