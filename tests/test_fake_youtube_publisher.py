import pytest

from app.services.fake_youtube_publisher import (
    FakeYouTubePublisher,
)
from app.services.youtube_publisher import (
    YouTubePublishResult,
)


def make_publication() -> dict:
    return {
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


def test_fake_youtube_publisher_success():
    publisher = FakeYouTubePublisher()

    result = publisher.publish(make_publication())

    assert isinstance(result, YouTubePublishResult)
    assert result.success is True
    assert result.youtube_video_id == "fake-youtube-video-id"
    assert result.youtube_url == (
        "https://www.youtube.com/watch?v=fake-youtube-video-id"
    )
    assert result.error is None


def test_fake_youtube_publisher_records_publication():
    publisher = FakeYouTubePublisher()
    publication = make_publication()

    publisher.publish(publication)

    assert publisher.published_publications == [publication]


def test_fake_youtube_publisher_failure():
    publisher = FakeYouTubePublisher(
        success=False,
        error="simulated upload failure",
    )

    result = publisher.publish(make_publication())

    assert isinstance(result, YouTubePublishResult)
    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert result.error == "simulated upload failure"
    assert publisher.published_publications == []


def test_fake_youtube_publisher_rejects_non_dict():
    publisher = FakeYouTubePublisher()

    with pytest.raises(TypeError, match="publication must be a dict"):
        publisher.publish("invalid")


def test_fake_youtube_publisher_can_use_custom_youtube_video_id():
    publisher = FakeYouTubePublisher(
        youtube_video_id="custom123",
    )

    result = publisher.publish(make_publication())

    assert result.success is True
    assert result.youtube_video_id == "custom123"
    assert result.youtube_url == (
        "https://www.youtube.com/watch?v=custom123"
    )
