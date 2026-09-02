import pytest

from app.services.fake_youtube_publisher import (
    FakeYouTubePublisher,
)
from app.services.youtube_publication_orchestration import (
    publish_youtube_publication,
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
        "youtube_video_id": None,
        "youtube_url": None,
        "error": None,
        "published_at": None,
    }


def test_orchestration_success(monkeypatch):
    publication = make_publication()
    stored = publication.copy()
    calls = []

    def fake_get(publication_id):
        assert publication_id == 1
        return stored

    def fake_mark_published(
        publication_id,
        youtube_video_id,
        youtube_url,
    ):
        calls.append(
            (
                "mark_published",
                publication_id,
                youtube_video_id,
                youtube_url,
            )
        )

        stored["status"] = "published"
        stored["youtube_video_id"] = youtube_video_id
        stored["youtube_url"] = youtube_url
        stored["error"] = None

        return True

    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "get_youtube_publication",
        fake_get,
    )
    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "mark_youtube_published",
        fake_mark_published,
    )

    publisher = FakeYouTubePublisher(
        youtube_video_id="fake123",
    )

    result = publish_youtube_publication(
        1,
        publisher,
    )

    assert publisher.published_publication is stored

    assert result["status"] == "published"
    assert result["youtube_video_id"] == "fake123"
    assert result["youtube_url"] == (
        "https://www.youtube.com/watch?v=fake123"
    )
    assert result["error"] is None

    assert calls == [
        (
            "mark_published",
            1,
            "fake123",
            "https://www.youtube.com/watch?v=fake123",
        )
    ]


def test_orchestration_failure(monkeypatch):
    publication = make_publication()
    stored = publication.copy()
    calls = []

    def fake_get(publication_id):
        assert publication_id == 1
        return stored

    def fake_update_status(
        publication_id,
        status,
        error=None,
    ):
        calls.append(
            (
                "update_status",
                publication_id,
                status,
                error,
            )
        )

        stored["status"] = status
        stored["error"] = error

        return True

    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "get_youtube_publication",
        fake_get,
    )
    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "update_youtube_publication_status",
        fake_update_status,
    )

    publisher = FakeYouTubePublisher(
        error="simulated upload failure",
    )

    result = publish_youtube_publication(
        1,
        publisher,
    )

    assert result["status"] == "failed"
    assert result["error"] == "simulated upload failure"
    assert result["youtube_video_id"] is None
    assert result["youtube_url"] is None

    assert calls == [
        (
            "update_status",
            1,
            "failed",
            "simulated upload failure",
        )
    ]


def test_orchestration_rejects_missing_publication(monkeypatch):
    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "get_youtube_publication",
        lambda publication_id: None,
    )

    publisher = FakeYouTubePublisher()

    with pytest.raises(
        ValueError,
        match=r"^YouTube publication not found: 999$",
    ):
        publish_youtube_publication(
            999,
            publisher,
        )


def test_orchestration_rejects_non_pending_publication(
    monkeypatch,
):
    publication = make_publication()
    publication["status"] = "published"

    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "get_youtube_publication",
        lambda publication_id: publication,
    )

    publisher = FakeYouTubePublisher()

    with pytest.raises(
        ValueError,
        match=r"^YouTube publication is not pending: 1$",
    ):
        publish_youtube_publication(
            1,
            publisher,
        )


def test_orchestration_rejects_invalid_publisher_result(
    monkeypatch,
):
    publication = make_publication()

    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "get_youtube_publication",
        lambda publication_id: publication,
    )

    class InvalidPublisher:
        def publish(self, publication):
            return {"success": True}

    with pytest.raises(
        TypeError,
        match=(
            r"^publisher\.publish\(\) must return "
            r"YouTubePublishResult$"
        ),
    ):
        publish_youtube_publication(
            1,
            InvalidPublisher(),
        )


def test_orchestration_rejects_success_without_video_id(
    monkeypatch,
):
    publication = make_publication()

    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "get_youtube_publication",
        lambda publication_id: publication,
    )

    class PublisherWithoutVideoId:
        def publish(self, publication):
            return YouTubePublishResult(
                success=True,
                youtube_url="https://youtube.test/video",
            )

    with pytest.raises(
        ValueError,
        match=(
            r"^Successful publication must provide "
            r"youtube_video_id$"
        ),
    ):
        publish_youtube_publication(
            1,
            PublisherWithoutVideoId(),
        )


def test_orchestration_rejects_success_without_url(
    monkeypatch,
):
    publication = make_publication()

    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "get_youtube_publication",
        lambda publication_id: publication,
    )

    class PublisherWithoutUrl:
        def publish(self, publication):
            return YouTubePublishResult(
                success=True,
                youtube_video_id="fake123",
            )

    with pytest.raises(
        ValueError,
        match=(
            r"^Successful publication must provide "
            r"youtube_url$"
        ),
    ):
        publish_youtube_publication(
            1,
            PublisherWithoutUrl(),
        )


def test_orchestration_returns_persisted_state(
    monkeypatch,
):
    publication = make_publication()
    stored = publication.copy()
    get_calls = []

    def fake_get(publication_id):
        get_calls.append(publication_id)
        return stored

    def fake_mark_published(
        publication_id,
        youtube_video_id,
        youtube_url,
    ):
        stored["status"] = "published"
        stored["youtube_video_id"] = youtube_video_id
        stored["youtube_url"] = youtube_url
        stored["error"] = None
        return True

    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "get_youtube_publication",
        fake_get,
    )
    monkeypatch.setattr(
        "app.services.youtube_publication_orchestration."
        "mark_youtube_published",
        fake_mark_published,
    )

    publisher = FakeYouTubePublisher(
        youtube_video_id="persisted123",
    )

    result = publish_youtube_publication(
        1,
        publisher,
    )

    assert get_calls == [1, 1]
    assert result is stored
    assert result["status"] == "published"
    assert result["youtube_video_id"] == "persisted123"
    assert result["youtube_url"] == (
        "https://www.youtube.com/watch?v=persisted123"
    )
