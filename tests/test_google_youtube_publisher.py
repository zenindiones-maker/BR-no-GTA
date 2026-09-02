from pathlib import Path

import pytest
import app.services.google_youtube_publisher as publisher_module
from app.services.google_youtube_publisher import (
    GoogleYouTubePublisher,
)
from app.services.youtube_publisher import (
    YouTubePublishResult,
)


class FakeRequest:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.execute_calls = 0

    def execute(self):
        self.execute_calls += 1

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
        self.request = request
        self.videos_calls = 0
        self.videos_resource = FakeVideosResource(request)

    def videos(self):
        self.videos_calls += 1
        return self.videos_resource


class FakeMediaFileUpload:
    calls = []

    def __init__(self, filename, chunksize, resumable):
        self.filename = filename
        self.chunksize = chunksize
        self.resumable = resumable

        type(self).calls.append(
            {
                "filename": filename,
                "chunksize": chunksize,
                "resumable": resumable,
            }
        )


def test_google_youtube_publisher_requires_service():
    try:
        GoogleYouTubePublisher(
            youtube_service=None,
        )
    except ValueError as exc:
        assert str(exc) == "youtube_service is required"
    else:
        raise AssertionError(
            "Expected ValueError when youtube_service is None"
        )


def test_instantiation_does_not_execute_youtube_upload():
    request = FakeRequest(
        response={"id": "never-used"},
    )
    service = FakeYouTubeService(request)

    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    assert isinstance(
        publisher,
        GoogleYouTubePublisher,
    )

    assert service.videos_calls == 0
    assert service.videos_resource.insert_calls == []
    assert request.execute_calls == 0


def test_publish_executes_upload_and_returns_youtube_publish_result(
    monkeypatch,
    tmp_path,
):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    request = FakeRequest(
        response={"id": "abc123"},
    )
    service = FakeYouTubeService(request)

    FakeMediaFileUpload.calls = []

    monkeypatch.setattr(
        publisher_module,
        "MediaFileUpload",
        FakeMediaFileUpload,
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    publication = {
        "file_path": str(video_file),
        "title": "BR no GTA",
        "description": "Descrição do vídeo",
        "tags": ["GTA", "BR", "YouTube"],
        "category_id": "20",
        "privacy_status": "private",
    }

    result = publisher.publish(publication)

    assert isinstance(
        result,
        YouTubePublishResult,
    )

    assert result.success is True
    assert result.youtube_video_id == "abc123"
    assert (
        result.youtube_url
        == "https://www.youtube.com/watch?v=abc123"
    )
    assert result.error is None

    assert service.videos_calls == 1
    assert len(service.videos_resource.insert_calls) == 1
    assert request.execute_calls == 1

    media_upload_calls = FakeMediaFileUpload.calls

    assert media_upload_calls == [
        {
            "filename": str(video_file),
            "chunksize": -1,
            "resumable": True,
        }
    ]

    insert_call = service.videos_resource.insert_calls[0]

    assert insert_call["part"] == "snippet,status"
    assert isinstance(
        insert_call["media_body"],
        FakeMediaFileUpload,
    )

    assert insert_call["body"] == {
        "snippet": {
            "title": "BR no GTA",
            "description": "Descrição do vídeo",
            "tags": ["GTA", "BR", "YouTube"],
            "categoryId": "20",
        },
        "status": {
            "privacyStatus": "private",
        },
    }


def test_publish_includes_publish_at_when_provided(
    monkeypatch,
    tmp_path,
):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    request = FakeRequest(
        response={"id": "scheduled123"},
    )
    service = FakeYouTubeService(request)

    monkeypatch.setattr(
        publisher_module,
        "MediaFileUpload",
        FakeMediaFileUpload,
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    result = publisher.publish(
        {
            "file_path": str(video_file),
            "title": "Vídeo agendado",
            "publish_at": "2026-09-10T18:00:00Z",
        }
    )

    assert result.success is True
    assert result.youtube_video_id == "scheduled123"

    insert_call = service.videos_resource.insert_calls[0]

    assert insert_call["body"]["status"] == {
        "privacyStatus": "private",
        "publishAt": "2026-09-10T18:00:00Z",
    }


def test_publish_requires_publication_dict():
    publisher = GoogleYouTubePublisher(
        youtube_service=FakeYouTubeService(
            FakeRequest(),
        ),
    )

    try:
        publisher.publish(None)
    except TypeError as exc:
        assert str(exc) == "publication must be a dict"
    else:
        raise AssertionError(
            "Expected TypeError when publication is not a dict"
        )


def test_publish_requires_file_path():
    publisher = GoogleYouTubePublisher(
        youtube_service=FakeYouTubeService(
            FakeRequest(),
        ),
    )

    result = publisher.publish(
        {
            "title": "Vídeo",
        }
    )

    assert result == YouTubePublishResult(
        success=False,
        error="publication file_path is required",
    )


def test_publish_requires_existing_video_file():
    missing_file = Path(
        "/tmp/br-no-gta-video-does-not-exist.mp4"
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=FakeYouTubeService(
            FakeRequest(),
        ),
    )

    result = publisher.publish(
        {
            "file_path": str(missing_file),
            "title": "Vídeo",
        }
    )

    assert result == YouTubePublishResult(
        success=False,
        error=(
            "video file not found: "
            f"{missing_file}"
        ),
    )


def test_publish_requires_title(tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    publisher = GoogleYouTubePublisher(
        youtube_service=FakeYouTubeService(
            FakeRequest(),
        ),
    )

    result = publisher.publish(
        {
            "file_path": str(video_file),
        }
    )

    assert result == YouTubePublishResult(
        success=False,
        error="publication title is required",
    )


def test_publish_fails_when_youtube_response_has_no_video_id(
    monkeypatch,
    tmp_path,
):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    request = FakeRequest(
        response={},
    )
    service = FakeYouTubeService(request)

    monkeypatch.setattr(
        publisher_module,
        "MediaFileUpload",
        FakeMediaFileUpload,
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    result = publisher.publish(
        {
            "file_path": str(video_file),
            "title": "Vídeo",
        }
    )

    assert result == YouTubePublishResult(
        success=False,
        error=(
            "YouTube API response did not "
            "contain video id"
        ),
    )

    assert service.videos_calls == 1
    assert request.execute_calls == 1


def test_publish_converts_youtube_api_exception_to_failure(
    monkeypatch,
    tmp_path,
):
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    request = FakeRequest(
        error=RuntimeError("simulated YouTube API failure"),
    )
    service = FakeYouTubeService(request)

    monkeypatch.setattr(
        publisher_module,
        "MediaFileUpload",
        FakeMediaFileUpload,
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    result = publisher.publish(
        {
            "file_path": str(video_file),
            "title": "Vídeo",
        }
    )

    assert result == YouTubePublishResult(
        success=False,
        error="simulated YouTube API failure",
    )

    assert service.videos_calls == 1
    assert len(service.videos_resource.insert_calls) == 1
    assert request.execute_calls == 1

def test_google_youtube_publisher_rejects_invalid_publication():
    publisher = GoogleYouTubePublisher(
        youtube_service=FakeYouTubeService(
            FakeRequest(),
        ),
    )

    with pytest.raises(
        TypeError,
        match="publication must be a dict",
    ):
        publisher.publish("invalid")


def test_google_youtube_publisher_contract_preserves_complete_publication_metadata(
    monkeypatch,
    tmp_path,
):
    video_file = tmp_path / "br-no-gta.mp4"
    video_file.write_bytes(b"fake mp4")

    request = FakeRequest(
        response={
            "id": "contract-video-001",
            "snippet": {
                "title": "GTA 6 — O que mudou",
            },
        },
    )

    service = FakeYouTubeService(request)

    FakeMediaFileUpload.calls = []

    monkeypatch.setattr(
        publisher_module,
        "MediaFileUpload",
        FakeMediaFileUpload,
    )

    publisher = GoogleYouTubePublisher(
        youtube_service=service,
    )

    publication = {
        "id": 77,
        "video_id": 42,
        "content_item_id": 21,
        "title": "GTA 6 — O que mudou",
        "description": (
            "Análise editorial do GTA 6 para o canal BR no GTA."
        ),
        "tags": [
            "GTA 6",
            "GTA VI",
            "Rockstar Games",
            "BR no GTA",
        ],
        "category_id": "20",
        "privacy_status": "private",
        "publish_at": None,
        "file_path": str(video_file),
    }

    result = publisher.publish(publication)

    assert result == YouTubePublishResult(
        success=True,
        youtube_video_id="contract-video-001",
        youtube_url=(
            "https://www.youtube.com/watch?v=contract-video-001"
        ),
        error=None,
    )

    assert service.videos_calls == 1
    assert request.execute_calls == 1

    assert len(service.videos_resource.insert_calls) == 1

    insert_call = service.videos_resource.insert_calls[0]

    assert insert_call["part"] == "snippet,status"

    media_body = insert_call["media_body"]

    assert isinstance(
        media_body,
        FakeMediaFileUpload,
    )

    assert media_body.filename == str(video_file)
    assert media_body.chunksize == -1
    assert media_body.resumable is True

    assert insert_call["body"] == {
        "snippet": {
            "title": "GTA 6 — O que mudou",
            "description": (
                "Análise editorial do GTA 6 para o canal BR no GTA."
            ),
            "tags": [
                "GTA 6",
                "GTA VI",
                "Rockstar Games",
                "BR no GTA",
            ],
            "categoryId": "20",
        },
        "status": {
            "privacyStatus": "private",
        },
    }
