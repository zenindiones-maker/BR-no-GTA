import json

import pytest

from app.database.connection import get_connection
from app.database.youtube_public_transition_repository import (
    get_youtube_public_transition,
)
from app.database.youtube_repository import (
    get_youtube_publication,
    insert_youtube_publication,
)
from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.harness_authorization_service import (
    issue_harness_authorization,
    resolve_harness_authorization,
)
from app.services.youtube_publication_orchestration import (
    make_youtube_publication_public,
    reconcile_youtube_publication_visibility,
    upload_youtube_publication,
)
from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)
from tests.test_youtube_repository import _create_video


def _publication_authorization(publication_id: int):
    return issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": "route-public-test",
            "capability_id": "youtube.publish-public",
            "selected_executor_binding": (
                "app.services.youtube_publication_orchestration."
                "make_youtube_publication_public"
            ),
            "publication_id": publication_id,
            "approval_source": "user",
            "approval_operation": "br_youtube_pode_postar",
            "fallback_occurred": False,
        },
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


def _create_uploaded_cloud_publication() -> int:
    publication_id = _create_publication()
    upload_youtube_publication(
        publication_id,
        FakeYouTubePublisher(
            upload_video_id="youtube123",
            upload_url="https://www.youtube.com/watch?v=youtube123",
        ),
    )
    cloud_execution = {
        "status": "SUCCEEDED",
        "execution_id": "upload-execution",
        "routing_id": "upload-route",
        "authorization_id": "upload-auth",
        "capability_id": "youtube.upload-private",
        "result": {
            "status": "UPLOADED",
            "publication_id": publication_id,
            "video_id": get_youtube_publication(publication_id)["video_id"],
        },
    }
    connection = get_connection()
    try:
        connection.execute(
            "UPDATE youtube_publications SET cloud_execution = ? WHERE id = ?",
            (json.dumps(cloud_execution, sort_keys=True), publication_id),
        )
        connection.commit()
    finally:
        connection.close()
    return publication_id


def test_upload_youtube_publication_success():
    publication_id = _create_publication()
    publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )
    result = upload_youtube_publication(publication_id, publisher)
    assert result["status"] == "uploaded"
    assert result["youtube_video_id"] == "youtube123"
    assert result["youtube_url"] == "https://www.youtube.com/watch?v=youtube123"
    assert result["error"] is None
    assert publisher.uploaded_publication is not None


def test_upload_youtube_publication_failure():
    publication_id = _create_publication()
    publisher = FakeYouTubePublisher(upload_success=False, upload_error="Falha de upload")
    result = upload_youtube_publication(publication_id, publisher)
    assert result["status"] == "failed"
    assert result["error"] == "Falha de upload"
    assert result["youtube_video_id"] is None


def test_upload_requires_pending_status():
    publication_id = _create_publication()
    publisher = FakeYouTubePublisher(
        upload_video_id="youtube123",
        upload_url="https://www.youtube.com/watch?v=youtube123",
    )
    upload_youtube_publication(publication_id, publisher)
    with pytest.raises(ValueError, match="not pending"):
        upload_youtube_publication(publication_id, publisher)


def test_invalid_upload_result_is_rejected():
    publication_id = _create_publication()

    class InvalidPublisher:
        def upload(self, publication):
            return "invalid"

    with pytest.raises(TypeError, match="YouTubeUploadResult"):
        upload_youtube_publication(publication_id, InvalidPublisher())


def test_make_public_requires_uploaded_status_before_side_effect():
    publication_id = _create_publication()
    publisher = FakeYouTubePublisher()
    with pytest.raises(ValueError, match="not uploaded"):
        make_youtube_publication_public(
            publication_id,
            publisher,
            authorization=_publication_authorization(publication_id),
        )
    assert publisher.made_public_video_ids == []


def test_make_public_rejects_missing_authorization_before_side_effect():
    publication_id = _create_uploaded_cloud_publication()
    publisher = FakeYouTubePublisher()
    with pytest.raises(PermissionError):
        make_youtube_publication_public(publication_id, publisher)
    assert publisher.made_public_video_ids == []


def test_make_public_requires_explicit_user_approval_lineage():
    publication_id = _create_uploaded_cloud_publication()
    authorization = issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": "route-public-test",
            "capability_id": "youtube.publish-public",
            "publication_id": publication_id,
            "fallback_occurred": False,
        },
    )
    publisher = FakeYouTubePublisher()
    with pytest.raises(PermissionError, match="explicit user approval"):
        make_youtube_publication_public(
            publication_id,
            publisher,
            authorization=authorization,
        )
    assert publisher.made_public_video_ids == []


def test_make_public_success_claims_once_consumes_auth_and_persists_transition():
    publication_id = _create_uploaded_cloud_publication()
    authorization = _publication_authorization(publication_id)
    publisher = FakeYouTubePublisher()
    result = make_youtube_publication_public(
        publication_id,
        publisher,
        authorization=authorization,
    )
    assert result["status"] == "published"
    assert publisher.made_public_video_ids == ["youtube123"]
    transition = get_youtube_public_transition(publication_id)
    assert transition["status"] == "PUBLISHED"
    assert transition["approval_source"] == "user"
    assert transition["approval_operation"] == "br_youtube_pode_postar"
    resolved = resolve_harness_authorization(
        authorization,
        allowed_statuses=("consumed",),
    )
    assert resolved.status == "consumed"


def test_make_public_remote_failure_becomes_uncertain_and_never_blind_retries():
    publication_id = _create_uploaded_cloud_publication()
    publisher = FakeYouTubePublisher(
        visibility_success=False,
        visibility_error="Falha de visibilidade",
    )
    result = make_youtube_publication_public(
        publication_id,
        publisher,
        authorization=_publication_authorization(publication_id),
    )
    assert result["status"] == "uploaded"
    assert result["publication_transition"] == "REMOTE_STATE_UNCERTAIN"
    transition = get_youtube_public_transition(publication_id)
    assert transition["status"] == "REMOTE_STATE_UNCERTAIN"
    second_publisher = FakeYouTubePublisher()
    with pytest.raises(ValueError, match="requires reconciliation"):
        make_youtube_publication_public(
            publication_id,
            second_publisher,
            authorization=_publication_authorization(publication_id),
        )
    assert second_publisher.made_public_video_ids == []


def test_reconcile_remote_public_finalizes_without_second_make_public():
    publication_id = _create_uploaded_cloud_publication()
    first = FakeYouTubePublisher(
        visibility_success=False,
        visibility_error="ambiguous transport failure",
    )
    make_youtube_publication_public(
        publication_id,
        first,
        authorization=_publication_authorization(publication_id),
    )
    observer = FakeYouTubePublisher(remote_privacy_status="public")
    result = reconcile_youtube_publication_visibility(publication_id, observer)
    assert result["status"] == "published"
    assert observer.visibility_queries == ["youtube123"]
    assert observer.made_public_video_ids == []
    assert get_youtube_public_transition(publication_id)["status"] == "PUBLISHED"


def test_reconcile_remote_private_allows_fresh_explicit_approval():
    publication_id = _create_uploaded_cloud_publication()
    first = FakeYouTubePublisher(
        visibility_success=False,
        visibility_error="ambiguous transport failure",
    )
    make_youtube_publication_public(
        publication_id,
        first,
        authorization=_publication_authorization(publication_id),
    )
    observer = FakeYouTubePublisher(remote_privacy_status="private")
    result = reconcile_youtube_publication_visibility(publication_id, observer)
    assert result["status"] == "uploaded"
    assert get_youtube_public_transition(publication_id)["status"] == "FAILED"

    second = FakeYouTubePublisher()
    published = make_youtube_publication_public(
        publication_id,
        second,
        authorization=_publication_authorization(publication_id),
    )
    assert published["status"] == "published"
    assert second.made_public_video_ids == ["youtube123"]


def test_invalid_visibility_result_marks_transition_uncertain():
    publication_id = _create_uploaded_cloud_publication()

    class InvalidPublisher:
        def make_public(self, youtube_video_id):
            return "invalid"

    with pytest.raises(TypeError, match="YouTubeVisibilityResult"):
        make_youtube_publication_public(
            publication_id,
            InvalidPublisher(),
            authorization=_publication_authorization(publication_id),
        )
    assert get_youtube_public_transition(publication_id)["status"] == "REMOTE_STATE_UNCERTAIN"
