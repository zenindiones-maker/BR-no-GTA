from unittest.mock import Mock

import pytest

from app.database.youtube_repository import (
    get_youtube_publication,
    insert_youtube_publication,
)
from app.services.google_youtube_publication_service import (
    PRIVATE_UPLOAD_CAPABILITY_ID,
    process_youtube_publication,
)
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.harness_youtube_publication_service import (
    publish_targeted_publication,
    upload_targeted_publication,
)
from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)
from tests.test_youtube_repository import _create_video


def _create_publication(title: str) -> int:
    content_item_id, video_id = _create_video()
    return insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title=title,
        description="Descrição",
        tags=["gta6"],
        category_id="20",
        file_path=f"/tmp/{title}.mp4",
        privacy_status="private",
        publish_at=None,
    )


def _target_authorization(publication_id: int):
    return issue_harness_authorization(
        authorized_action="YOUTUBE",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": "route-target-test",
            "capability_id": PRIVATE_UPLOAD_CAPABILITY_ID,
            "selected_executor_binding": "app.services.youtube_publication_orchestration",
            "publication_id": publication_id,
            "fallback_occurred": False,
        },
    )


def _publisher(video_id: str):
    publisher = Mock()
    publisher.upload.return_value = YouTubeUploadResult(
        success=True,
        youtube_video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
    )
    publisher.make_public.return_value = YouTubeVisibilityResult(success=True)
    return publisher


def test_targeted_upload_ignores_earlier_pending_publication(monkeypatch):
    first_id = _create_publication("first")
    target_id = _create_publication("target")
    publisher = _publisher("yt-target")
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service.create_google_youtube_publisher",
        lambda **kwargs: publisher,
    )
    authorization = _target_authorization(target_id)

    result = process_youtube_publication(
        target_id,
        authorization_to_context(authorization),
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    assert result["id"] == target_id
    assert result["status"] == "uploaded"
    assert result["youtube_video_id"] == "yt-target"
    assert get_youtube_publication(first_id)["status"] == "pending"
    assert get_youtube_publication(target_id)["status"] == "uploaded"


def test_targeted_upload_rejects_authorization_for_other_publication_before_side_effect(monkeypatch):
    first_id = _create_publication("first")
    target_id = _create_publication("target")
    factory = Mock()
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service.create_google_youtube_publisher",
        factory,
    )

    with pytest.raises(PermissionError, match="subject mismatch"):
        process_youtube_publication(
            target_id,
            authorization_to_context(_target_authorization(first_id)),
            token_file="/tmp/token.json",
            client_secrets_file="/tmp/client.json",
        )

    factory.assert_not_called()


def test_targeted_upload_rejects_wrong_capability_lineage(monkeypatch):
    publication_id = _create_publication("target")
    factory = Mock()
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service.create_google_youtube_publisher",
        factory,
    )
    authorization = issue_harness_authorization(
        authorized_action="YOUTUBE",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": "route-target-test",
            "capability_id": "video.render",
            "publication_id": publication_id,
        },
    )

    with pytest.raises(PermissionError, match="capability mismatch"):
        process_youtube_publication(
            publication_id,
            authorization_to_context(authorization),
            token_file="/tmp/token.json",
            client_secrets_file="/tmp/client.json",
        )

    factory.assert_not_called()


def test_targeted_upload_authorization_is_single_use(monkeypatch):
    publication_id = _create_publication("target")
    publisher = _publisher("yt-target")
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service.create_google_youtube_publisher",
        lambda **kwargs: publisher,
    )
    authorization = _target_authorization(publication_id)
    context = authorization_to_context(authorization)

    process_youtube_publication(
        publication_id,
        context,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    with pytest.raises((PermissionError, ValueError)):
        process_youtube_publication(
            publication_id,
            context,
            token_file="/tmp/token.json",
            client_secrets_file="/tmp/client.json",
        )
    assert publisher.upload.call_count == 1


def test_harness_targeted_upload_routes_exact_capability_and_returns_canonical_evidence(monkeypatch):
    publication_id = _create_publication("target")
    publisher = _publisher("yt-target")
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service.create_google_youtube_publisher",
        lambda **kwargs: publisher,
    )

    result = upload_targeted_publication(
        publication_id,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    assert result["publication"]["id"] == publication_id
    assert result["publication"]["status"] == "uploaded"
    assert result["routing"]["selected_capability_id"] == "youtube.upload-private"
    assert result["routing"]["fallback_occurred"] is False
    canonical = result["canonical_execution_result"]
    assert canonical["authority"] == "deepseek_harness"
    assert canonical["authorized_action"] == "YOUTUBE"
    assert canonical["capability_id"] == "youtube.upload-private"
    assert canonical["success"] is True


def test_public_gate_routes_exact_capability_and_cannot_publish_other_record(monkeypatch):
    first_id = _create_publication("first")
    target_id = _create_publication("target")
    publishers = {
        first_id: _publisher("yt-first"),
        target_id: _publisher("yt-target"),
    }
    current = {"publisher": publishers[target_id]}
    monkeypatch.setattr(
        "app.services.google_youtube_publication_service.create_google_youtube_publisher",
        lambda **kwargs: current["publisher"],
    )

    upload_targeted_publication(
        target_id,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )
    result = publish_targeted_publication(
        target_id,
        token_file="/tmp/token.json",
        client_secrets_file="/tmp/client.json",
    )

    assert result["publication"]["id"] == target_id
    assert result["publication"]["status"] == "published"
    assert result["routing"]["selected_capability_id"] == "youtube.publish-public"
    assert result["routing"]["fallback_occurred"] is False
    assert result["canonical_execution_result"]["success"] is True
    assert get_youtube_publication(first_id)["status"] == "pending"
    assert get_youtube_publication(target_id)["status"] == "published"
