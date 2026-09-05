from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)


def test_fake_upload_success() -> None:
    publisher = FakeYouTubePublisher(
        upload_video_id="abc123",
        upload_url="https://youtube.com/watch?v=abc123",
    )

    publication = {"id": 10}

    result = publisher.upload(publication)

    assert isinstance(result, YouTubeUploadResult)
    assert result.success is True
    assert result.youtube_video_id == "abc123"
    assert result.youtube_url == "https://youtube.com/watch?v=abc123"
    assert result.error is None
    assert publisher.uploaded_publication == publication
    assert publisher.uploaded_publications == [publication]


def test_fake_upload_failure() -> None:
    publisher = FakeYouTubePublisher(
        upload_success=False,
        upload_error="erro de upload",
    )

    result = publisher.upload({"id": 20})

    assert isinstance(result, YouTubeUploadResult)
    assert result.success is False
    assert result.error == "erro de upload"


def test_fake_make_public_success() -> None:
    publisher = FakeYouTubePublisher()

    result = publisher.make_public("abc123")

    assert isinstance(result, YouTubeVisibilityResult)
    assert result.success is True
    assert result.error is None
    assert publisher.made_public_video_ids == ["abc123"]


def test_fake_make_public_failure() -> None:
    publisher = FakeYouTubePublisher(
        visibility_success=False,
        visibility_error="erro de visibilidade",
    )

    result = publisher.make_public("abc123")

    assert isinstance(result, YouTubeVisibilityResult)
    assert result.success is False
    assert result.error == "erro de visibilidade"
    assert publisher.made_public_video_ids == []
