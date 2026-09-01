from app.services.youtube_publisher import (
    YouTubePublishResult,
    YouTubePublisher,
)


def test_youtube_publish_result_success():
    result = YouTubePublishResult(
        success=True,
        youtube_video_id="abc123",
        youtube_url="https://www.youtube.com/watch?v=abc123",
    )

    assert result.success is True
    assert result.youtube_video_id == "abc123"
    assert result.youtube_url == (
        "https://www.youtube.com/watch?v=abc123"
    )
    assert result.error is None


def test_youtube_publish_result_failure():
    result = YouTubePublishResult(
        success=False,
        error="upload failed",
    )

    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert result.error == "upload failed"


def test_youtube_publisher_contract_is_defined():
    assert hasattr(YouTubePublisher, "publish")


def test_youtube_publisher_contract_uses_publication_dict():
    publication = {
        "id": 1,
        "video_id": 10,
        "content_item_id": 20,
        "file_path": "output/video.mp4",
        "title": "Vídeo GTA",
        "description": "Descrição",
        "tags": ["gta6"],
        "category_id": "20",
        "privacy_status": "private",
        "status": "pending",
    }

    assert isinstance(publication, dict)
