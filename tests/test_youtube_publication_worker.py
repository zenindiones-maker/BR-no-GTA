import pytest

from app.services.harness_authorization_service import issue_harness_authorization

from app.database.youtube_repository import (
    get_youtube_publication,
    insert_youtube_publication,
)
from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.youtube_publication_worker import (
    execute_youtube_publication,
    execute_youtube_upload,
)
from tests.test_youtube_repository import _create_video


def _authorization(publication_id):
    return issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": f"test-publication-worker-route-{publication_id}",
            "capability_id": "youtube.publish-public",
            "publication_id": publication_id,
            "fallback_occurred": False,
            "approval_source": "user",
            "approval_operation": "br_youtube_pode_postar",
        },
    )


def _create_publication() -> int:
    content_item_id, video_id = _create_video()

    return insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Teste Worker",
        description="Descrição",
        tags=["gta6"],
        category_id="20",
        file_path="/tmp/video.mp4",
        privacy_status="private",
        publish_at=None,
    )


def test_execute_youtube_upload_delegates_upload():
    publication_id = _create_publication()

    publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )

    result = execute_youtube_upload(
        publication_id=publication_id,
        publisher=publisher,
    )

    assert result["status"] == "uploaded"
    assert result["youtube_video_id"] == "youtube123"
    assert publisher.uploaded_publication is not None


def test_execute_youtube_publication_delegates_visibility():
    publication_id = _create_publication()

    upload_publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )

    execute_youtube_upload(
        publication_id=publication_id,
        publisher=upload_publisher,
    )

    publisher = FakeYouTubePublisher()

    result = execute_youtube_publication(
        publication_id=publication_id,
        publisher=publisher,
        authorization=_authorization(publication_id),
    )

    assert result["status"] == "published"
    assert result["youtube_video_id"] == "youtube123"
    assert publisher.made_public_video_ids == ["youtube123"]


def test_execute_youtube_publication_keeps_uploaded_on_visibility_failure():
    publication_id = _create_publication()

    upload_publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )

    execute_youtube_upload(
        publication_id=publication_id,
        publisher=upload_publisher,
    )

    publisher = FakeYouTubePublisher(
        visibility_success=False,
        visibility_error="Falha de visibilidade",
    )

    result = execute_youtube_publication(
        publication_id=publication_id,
        publisher=publisher,
        authorization=_authorization(publication_id),
    )

    assert result["status"] == "uploaded"
    assert result["youtube_video_id"] == "youtube123"
    assert result["error"] == "Falha de visibilidade"


def test_execute_youtube_upload_rejects_invalid_publication_id():
    publisher = FakeYouTubePublisher()

    with pytest.raises(
        ValueError,
        match="publication_id must be a positive integer",
    ):
        execute_youtube_upload(
            publication_id=0,
            publisher=publisher,
        )


def test_execute_youtube_publication_rejects_invalid_publication_id():
    publisher = FakeYouTubePublisher()

    with pytest.raises(
        ValueError,
        match="publication_id must be a positive integer",
    ):
        execute_youtube_publication(
            publication_id=0,
            publisher=publisher,
        )


def test_execute_youtube_upload_requires_publisher():
    publication_id = _create_publication()

    with pytest.raises(
        ValueError,
        match="publisher is required",
    ):
        execute_youtube_upload(
            publication_id=publication_id,
            publisher=None,
        )


def test_execute_youtube_publication_requires_publisher():
    publication_id = _create_publication()

    with pytest.raises(
        ValueError,
        match="publisher is required",
    ):
        execute_youtube_publication(
            publication_id=publication_id,
            publisher=None,
        )