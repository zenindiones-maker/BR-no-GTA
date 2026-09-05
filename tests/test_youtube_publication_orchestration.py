import pytest

from app.database.youtube_repository import (
    get_youtube_publication,
    insert_youtube_publication,
)
from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.youtube_publication_orchestration import (
    make_youtube_publication_public,
    upload_youtube_publication,
)
from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)

from tests.test_youtube_repository import (
    _create_video,
)


def _create_publication() -> int:
    content_item_id, video_id = _create_video()

    return insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Teste YouTube",
        description="Descrição",
        tags=["gta6"],
        category_id="20",
        file_path="/tmp/video.mp4",
        privacy_status="private",
        publish_at=None,
    )


def test_upload_youtube_publication_success():
    publication_id = _create_publication()

    publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )

    result = upload_youtube_publication(
        publication_id,
        publisher,
    )

    assert result["status"] == "uploaded"
    assert result["youtube_video_id"] == "youtube123"
    assert result["youtube_url"] == (
        "https://www.youtube.com/watch?v=youtube123"
    )
    assert result["error"] is None
    assert publisher.uploaded_publication is not None


def test_make_youtube_publication_public_success():
    publication_id = _create_publication()

    upload_publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )

    upload_youtube_publication(
        publication_id,
        upload_publisher,
    )

    publisher = FakeYouTubePublisher()

    result = make_youtube_publication_public(
        publication_id,
        publisher,
    )

    assert result["status"] == "published"
    assert result["youtube_video_id"] == "youtube123"
    assert result["error"] is None
    assert publisher.made_public_video_ids == ["youtube123"]


def test_make_youtube_publication_public_failure_keeps_uploaded():
    publication_id = _create_publication()

    upload_publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )

    upload_youtube_publication(
        publication_id,
        upload_publisher,
    )

    publisher = FakeYouTubePublisher(
        visibility_success=False,
        visibility_error="Falha de visibilidade",
    )

    result = make_youtube_publication_public(
        publication_id,
        publisher,
    )

    assert result["status"] == "uploaded"
    assert result["youtube_video_id"] == "youtube123"
    assert result["youtube_url"] == (
        "https://www.youtube.com/watch?v=youtube123"
    )
    assert result["error"] == "Falha de visibilidade"


def test_upload_youtube_publication_failure():
    publication_id = _create_publication()

    publisher = FakeYouTubePublisher(
        upload_success=False,
        upload_error="Falha de upload",
    )

    result = upload_youtube_publication(
        publication_id,
        publisher,
    )

    assert result["status"] == "failed"
    assert result["error"] == "Falha de upload"
    assert result["youtube_video_id"] is None


def test_upload_requires_pending_status():
    publication_id = _create_publication()

    publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )

    upload_youtube_publication(
        publication_id,
        publisher,
    )

    with pytest.raises(ValueError, match="not pending"):
        upload_youtube_publication(
            publication_id,
            publisher,
        )


def test_make_public_requires_uploaded_status():
    publication_id = _create_publication()

    publisher = FakeYouTubePublisher()

    with pytest.raises(ValueError, match="not uploaded"):
        make_youtube_publication_public(
            publication_id,
            publisher,
        )


def test_invalid_upload_result_is_rejected():
    publication_id = _create_publication()

    class InvalidPublisher:
        def upload(self, publication):
            return "invalid"

        def make_public(self, youtube_video_id):
            return YouTubeVisibilityResult(success=True)

    with pytest.raises(
        TypeError,
        match="YouTubeUploadResult",
    ):
        upload_youtube_publication(
            publication_id,
            InvalidPublisher(),
        )


def test_invalid_visibility_result_is_rejected():
    publication_id = _create_publication()

    upload_publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )

    upload_youtube_publication(
        publication_id,
        upload_publisher,
    )

    class InvalidPublisher:
        def upload(self, publication):
            return YouTubeUploadResult(
                success=True,
                youtube_video_id="youtube123",
                youtube_url="https://www.youtube.com/watch?v=youtube123",
            )

        def make_public(self, youtube_video_id):
            return "invalid"

    with pytest.raises(
        TypeError,
        match="YouTubeVisibilityResult",
    ):
        make_youtube_publication_public(
            publication_id,
            InvalidPublisher(),
        )
