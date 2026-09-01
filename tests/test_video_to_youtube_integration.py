from app.database.youtube_repository import (
    get_youtube_publication_by_video_id,
)
from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.youtube_publication_orchestration import (
    publish_youtube_publication,
)
from app.services.youtube_service import (
    create_youtube_publish_spec,
    create_youtube_publication,
)


def test_video_can_reach_youtube_publication_and_be_published(
    monkeypatch,
):
    video = {
        "id": 1001,
        "content_item_id": 2001,
        "title": "BR no GTA — Teste de Integração",
        "status": "ready",
        "file_path": "/tmp/test-video.mp4",
    }

    publish_spec = create_youtube_publish_spec(video)

    assert publish_spec["video_id"] == video["id"]
    assert publish_spec["content_item_id"] == video["content_item_id"]
    assert publish_spec["title"] == video["title"]
    assert publish_spec["file_path"] == video["file_path"]

    publication = create_youtube_publication(publish_spec)

    assert publication["id"] > 0
    assert publication["video_id"] == video["id"]
    assert publication["status"] == "pending"

    persisted = get_youtube_publication_by_video_id(video["id"])

    assert persisted is not None
    assert persisted["id"] == publication["id"]
    assert persisted["status"] == "pending"

    publisher = FakeYouTubePublisher(
        success=True,
        youtube_video_id="integration-test-video-id",
    )

    result = publish_youtube_publication(
        publication["id"],
        publisher,
    )

    assert result["id"] == publication["id"]
    assert result["video_id"] == video["id"]
    assert result["status"] == "published"
    assert result["youtube_video_id"] == "integration-test-video-id"
    assert (
        result["youtube_url"]
        == "https://www.youtube.com/watch?v=integration-test-video-id"
    )

    persisted_after_publish = get_youtube_publication_by_video_id(
        video["id"]
    )

    assert persisted_after_publish is not None
    assert persisted_after_publish["status"] == "published"
    assert (
        persisted_after_publish["youtube_video_id"]
        == "integration-test-video-id"
    )

    assert publisher.published_publications == [persisted]
