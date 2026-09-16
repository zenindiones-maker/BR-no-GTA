import inspect

import pytest

from app.workers import youtube_private_upload_worker
from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.youtube_publication_orchestration import make_youtube_publication_public
from tests.test_youtube_publication_orchestration import (
    _create_uploaded_cloud_publication,
    _publication_authorization,
)


def test_already_published_never_repeats_external_side_effect():
    publication_id = _create_uploaded_cloud_publication()
    first = FakeYouTubePublisher()
    result = make_youtube_publication_public(
        publication_id,
        first,
        authorization=_publication_authorization(publication_id),
    )
    assert result["status"] == "published"
    assert first.made_public_video_ids == ["youtube123"]

    second = FakeYouTubePublisher()
    with pytest.raises(ValueError, match="not uploaded"):
        make_youtube_publication_public(
            publication_id,
            second,
            authorization=_publication_authorization(publication_id),
        )
    assert second.made_public_video_ids == []


def test_publication_a_authorization_cannot_publish_b():
    publication_a = _create_uploaded_cloud_publication()
    publication_b = _create_uploaded_cloud_publication()
    publisher = FakeYouTubePublisher()
    with pytest.raises(PermissionError):
        make_youtube_publication_public(
            publication_b,
            publisher,
            authorization=_publication_authorization(publication_a),
        )
    assert publisher.made_public_video_ids == []


def test_wrong_publication_capability_fails_before_side_effect():
    publication_id = _create_uploaded_cloud_publication()
    authorization = issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": "route-wrong-capability",
            "capability_id": "youtube.upload-private",
            "publication_id": publication_id,
            "approval_source": "user",
            "approval_operation": "br_youtube_pode_postar",
            "fallback_occurred": False,
        },
    )
    publisher = FakeYouTubePublisher()
    with pytest.raises(PermissionError, match="capability mismatch"):
        make_youtube_publication_public(
            publication_id,
            publisher,
            authorization=authorization,
        )
    assert publisher.made_public_video_ids == []


def test_fallback_publication_authorization_fails_before_side_effect():
    publication_id = _create_uploaded_cloud_publication()
    authorization = issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": "route-fallback",
            "capability_id": "youtube.publish-public",
            "publication_id": publication_id,
            "approval_source": "user",
            "approval_operation": "br_youtube_pode_postar",
            "fallback_occurred": True,
        },
    )
    publisher = FakeYouTubePublisher()
    with pytest.raises(PermissionError, match="may not use fallback"):
        make_youtube_publication_public(
            publication_id,
            publisher,
            authorization=authorization,
        )
    assert publisher.made_public_video_ids == []


def test_private_upload_worker_has_no_publication_side_effect_boundary():
    source = inspect.getsource(youtube_private_upload_worker)
    assert ".make_public(" not in source
    assert "br_youtube_pode_postar" not in source
    assert 'authorized_action") != "YOUTUBE"' in source
