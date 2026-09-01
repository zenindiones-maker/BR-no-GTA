from pathlib import Path

import pytest

from app.services.google_youtube_publisher import (
    GoogleYouTubePublisher,
)
from app.services.youtube_publisher import YouTubePublishResult


class FakeRequest:
    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error

    def execute(self):
        if self.error is not None:
            raise self.error

        return self.response


class FakeVideosResource:
    def __init__(self, request):
        self.request = request
        self.insert_calls = []

    def insert(self, **kwargs):
        self.insert_calls.append(kwargs)
        return self.request


class FakeYouTubeService:
    def __init__(self, request):
        self.videos_resource = FakeVideosResource(request)
        self.videos_calls = 0

    def videos(self):
        self.videos_calls += 1
        return self.videos_resource


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"fake video content")
    return path


def make_publication(video_file: Path) -> dict:
    return {
        "id": 123,
        "file_path": str(video_file),
        "title": "Vídeo GTA",
        "description": "Descrição do vídeo",
        "tags": ["GTA", "GTA 6"],
        "category_id": "20",
        "privacy_status": "private",
    }


def test_google_youtube_publisher_returns_success(video_file):
    request = FakeRequest(
        response={"id": "youtube-123"},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    result = publisher.publish(
        make_publication(video_file),
    )

    assert isinstance(result, YouTubePublishResult)
    assert result.success is True
    assert result.youtube_video_id == "youtube-123"
    assert (
        result.youtube_url
        == "https://www.youtube.com/watch?v=youtube-123"
    )
    assert result.error is None


def test_google_youtube_publisher_calls_youtube_api(video_file):
    request = FakeRequest(
        response={"id": "youtube-456"},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    publisher.publish(make_publication(video_file))

    assert service.videos_calls == 1
    assert len(service.videos_resource.insert_calls) == 1


def test_google_youtube_publisher_builds_metadata(video_file):
    request = FakeRequest(
        response={"id": "youtube-789"},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    publisher.publish(make_publication(video_file))

    call = service.videos_resource.insert_calls[0]

    assert call["part"] == "snippet,status"

    assert call["body"]["snippet"] == {
        "title": "Vídeo GTA",
        "description": "Descrição do vídeo",
        "tags": ["GTA", "GTA 6"],
        "categoryId": "20",
    }

    assert call["body"]["status"] == {
        "privacyStatus": "private",
    }


def test_google_youtube_publisher_accepts_publish_at(video_file):
    request = FakeRequest(
        response={"id": "youtube-scheduled"},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    publication = make_publication(video_file)
    publication["publish_at"] = "2026-09-10T18:00:00Z"

    publisher.publish(publication)

    call = service.videos_resource.insert_calls[0]

    assert call["body"]["status"] == {
        "privacyStatus": "private",
        "publishAt": "2026-09-10T18:00:00Z",
    }


def test_google_youtube_publisher_creates_media_upload(
    video_file,
):
    request = FakeRequest(
        response={"id": "youtube-upload"},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    result = publisher.publish(make_publication(video_file))

    assert result.success is True

    assert len(service.videos_resource.insert_calls) == 1

    call = service.videos_resource.insert_calls[0]

    assert call["part"] == "snippet,status"
    assert call["media_body"] is not None
    assert call["media_body"].__class__.__name__ == "MediaFileUpload"


def test_google_youtube_publisher_rejects_missing_file():
    request = FakeRequest(
        response={"id": "unused"},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    publication = {
        "file_path": "/does/not/exist/video.mp4",
        "title": "Vídeo GTA",
    }

    result = publisher.publish(publication)

    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert "video file not found" in result.error


def test_google_youtube_publisher_rejects_missing_title(
    video_file,
):
    request = FakeRequest(
        response={"id": "unused"},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    publication = {
        "file_path": str(video_file),
    }

    result = publisher.publish(publication)

    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert result.error == "publication title is required"


def test_google_youtube_publisher_rejects_invalid_publication():
    request = FakeRequest(
        response={"id": "unused"},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    with pytest.raises(TypeError, match="publication must be a dict"):
        publisher.publish("invalid")


def test_google_youtube_publisher_requires_service():
    with pytest.raises(
        ValueError,
        match="youtube_service is required",
    ):
        GoogleYouTubePublisher(youtube_service=None)


def test_google_youtube_publisher_handles_missing_video_id(
    video_file,
):
    request = FakeRequest(
        response={},
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    result = publisher.publish(
        make_publication(video_file),
    )

    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert (
        result.error
        == "YouTube API response did not contain video id"
    )


def test_google_youtube_publisher_handles_api_error(video_file):
    request = FakeRequest(
        error=RuntimeError("simulated YouTube API failure"),
    )
    service = FakeYouTubeService(request)
    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    result = publisher.publish(
        make_publication(video_file),
    )

    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert result.error == "simulated YouTube API failure"
