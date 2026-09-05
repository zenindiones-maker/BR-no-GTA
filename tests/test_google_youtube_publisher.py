from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.google_youtube_publisher import GoogleYouTubePublisher
from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)


def test_upload_requires_file_path() -> None:
    publisher = GoogleYouTubePublisher(MagicMock())

    result = publisher.upload({"title": "Teste"})

    assert isinstance(result, YouTubeUploadResult)
    assert result.success is False
    assert result.error == "YouTube publication requires file_path"


def test_upload_requires_title(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")

    publisher = GoogleYouTubePublisher(MagicMock())

    result = publisher.upload({"file_path": str(video)})

    assert result.success is False
    assert result.error == "YouTube publication requires title"


def test_upload_uses_private_visibility(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")

    service = MagicMock()

    request = MagicMock()
    request.execute.return_value = {"id": "abc123"}

    service.videos.return_value.insert.return_value = request

    publisher = GoogleYouTubePublisher(service)

    with patch(
        "app.services.google_youtube_publisher.MediaFileUpload"
    ) as media_upload:
        result = publisher.upload(
            {
                "file_path": str(video),
                "title": "Teste",
                "description": "Descrição",
                "tags": ["gta6"],
                "category_id": "20",
            }
        )

    assert result.success is True
    assert result.youtube_video_id == "abc123"
    assert result.youtube_url == "https://www.youtube.com/watch?v=abc123"

    media_upload.assert_called_once_with(
        str(video),
        resumable=True,
    )

    service.videos.return_value.insert.assert_called_once_with(
        part="snippet,status",
        body={
            "snippet": {
                "title": "Teste",
                "description": "Descrição",
                "tags": ["gta6"],
                "categoryId": "20",
            },
            "status": {
                "privacyStatus": "private",
            },
        },
        media_body=media_upload.return_value,
    )


def test_make_public() -> None:
    service = MagicMock()

    request = MagicMock()
    service.videos.return_value.update.return_value = request

    publisher = GoogleYouTubePublisher(service)

    result = publisher.make_public("abc123")

    assert isinstance(result, YouTubeVisibilityResult)
    assert result.success is True

    service.videos.return_value.update.assert_called_once_with(
        part="status",
        body={
            "id": "abc123",
            "status": {
                "privacyStatus": "public",
            },
        },
    )


def test_make_public_requires_video_id() -> None:
    publisher = GoogleYouTubePublisher(MagicMock())

    result = publisher.make_public("")

    assert result.success is False
    assert result.error == "youtube_video_id is required"
