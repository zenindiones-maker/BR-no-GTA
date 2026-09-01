from dataclasses import dataclass

from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.youtube_publisher import PublishResult


@dataclass
class FakePublication:
    id: int = 123


def test_fake_youtube_publisher_implements_publish():
    publisher = FakeYouTubePublisher()

    assert callable(publisher.publish)


def test_fake_youtube_publisher_returns_success():
    publication = FakePublication()
    publisher = FakeYouTubePublisher(
        youtube_video_id="fake-123",
        youtube_url="https://youtube.com/watch?v=fake-123",
    )

    result = publisher.publish(publication)

    assert isinstance(result, PublishResult)
    assert result.success is True
    assert result.youtube_video_id == "fake-123"
    assert result.youtube_url == "https://youtube.com/watch?v=fake-123"
    assert result.error is None


def test_fake_youtube_publisher_receives_publication():
    publication = FakePublication()
    publisher = FakeYouTubePublisher()

    publisher.publish(publication)

    assert publisher.published_publication is publication


def test_fake_youtube_publisher_returns_failure():
    publication = FakePublication()
    publisher = FakeYouTubePublisher(
        error="simulated upload failure",
    )

    result = publisher.publish(publication)

    assert isinstance(result, PublishResult)
    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert result.error == "simulated upload failure"
