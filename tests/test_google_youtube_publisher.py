from pathlib import Path

from app.services.google_youtube_publisher import (
    GoogleYouTubePublisher,
)
from app.services.youtube_publisher import (
    YouTubePublishResult,
)


class FakeUploadRequest:
    def __init__(self, response):
        self.response = response
        self.executed = False

    def execute(self):
        self.executed = True
        return self.response


class FakeVideosResource:
    def __init__(self, response):
        self.response = response
        self.received_part = None
        self.received_body = None
        self.received_media_body = None

    def insert(self, *, part, body, media_body):
        self.received_part = part
        self.received_body = body
        self.received_media_body = media_body

        return FakeUploadRequest(self.response)


class FakeYouTubeService:
    def __init__(self, response):
        self.videos_resource = FakeVideosResource(response)

    def videos(self):
        return self.videos_resource


def publication(
    file_path: str,
) -> dict:
    return {
        "id": 10,
        "video_id": 20,
        "content_item_id": 30,
        "file_path": file_path,
        "title": "Vídeo de teste",
        "description": "Descrição de teste",
        "tags": ["gta", "brasil"],
        "category_id": "20",
        "privacy_status": "private",
        "publish_at": None,
        "status": "pending",
    }


def test_google_publisher_implements_publish_contract(tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake mp4")

    youtube = FakeYouTubeService(
        {"id": "google-video-123"}
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=youtube,
    )

    result = publisher.publish(
        publication(str(video_file))
    )

    assert isinstance(result, YouTubePublishResult)
    assert result.success is True
    assert result.youtube_video_id == "google-video-123"
    assert (
        result.youtube_url
        == "https://www.youtube.com/watch?v=google-video-123"
    )


def test_google_publisher_builds_youtube_request(tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake mp4")

    youtube = FakeYouTubeService(
        {"id": "google-video-456"}
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=youtube,
    )

    publisher.publish(
        publication(str(video_file))
    )

    videos = youtube.videos_resource

    assert videos.received_part == "snippet,status"

    assert videos.received_body == {
        "snippet": {
            "title": "Vídeo de teste",
            "description": "Descrição de teste",
            "tags": ["gta", "brasil"],
            "categoryId": "20",
        },
        "status": {
            "privacyStatus": "private",
        },
    }

    assert videos.received_media_body is not None


def test_google_publisher_returns_failure_when_api_fails(tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake mp4")

    class FailingUploadRequest:
        def execute(self):
            raise RuntimeError("Google API failure")

    class FailingVideosResource:
        def insert(self, *, part, body, media_body):
            return FailingUploadRequest()

    class FailingYouTubeService:
        def videos(self):
            return FailingVideosResource()

    publisher = GoogleYouTubePublisher(
        youtube_service=FailingYouTubeService(),
    )

    result = publisher.publish(
        publication(str(video_file))
    )

    assert isinstance(result, YouTubePublishResult)
    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert "Google API failure" in result.error


def test_google_publisher_rejects_missing_file():
    youtube = FakeYouTubeService(
        {"id": "google-video-789"}
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=youtube,
    )

    result = publisher.publish(
        publication("/tmp/arquivo-que-nao-existe.mp4")
    )

    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert result.error is not None
