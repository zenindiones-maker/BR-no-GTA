from app.database.content_repository import insert_content_item
from app.database.schema import initialize_schema
from app.database.video_repository import insert_video
from app.database.youtube_repository import (
    get_youtube_publication_by_video_id,
)
from app.services.fake_youtube_publisher import FakeYouTubePublisher
from app.services.youtube_publication_orchestration import (
    upload_youtube_publication,
)
from app.services.youtube_service import (
    create_youtube_publish_spec,
    create_youtube_publication,
)


def test_video_can_reach_youtube_publication_and_be_uploaded(
    monkeypatch,
):
    initialize_schema()

    content_item_id = insert_content_item(
        title="BR no GTA — Conteúdo de Integração",
        content_type="video",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="BR no GTA — Teste de Integração",
        status="ready",
        file_path="/tmp/test-video.mp4",
    )

    video = {
        "id": video_id,
        "content_item_id": content_item_id,
        "title": "BR no GTA — Teste de Integração",
        "status": "ready",
        "file_path": "/tmp/test-video.mp4",
    }

    publish_spec = create_youtube_publish_spec(video)

    assert publish_spec["video_id"] == video["id"]
    assert (
        publish_spec["content_item_id"]
        == video["content_item_id"]
    )
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
        upload_video_id="integration-test-video-id",
        upload_url=(
            "https://www.youtube.com/watch?v="
            "integration-test-video-id"
        ),
    )

    result = upload_youtube_publication(
        publication["id"],
        publisher,
    )

    assert result["id"] == publication["id"]
    assert result["video_id"] == video["id"]
    assert result["status"] == "uploaded"
    assert (
        result["youtube_video_id"]
        == "integration-test-video-id"
    )
    assert (
        result["youtube_url"]
        == (
            "https://www.youtube.com/watch?v="
            "integration-test-video-id"
        )
    )

    persisted_after_upload = (
        get_youtube_publication_by_video_id(video["id"])
    )

    assert persisted_after_upload is not None
    assert persisted_after_upload["status"] == "uploaded"
    assert (
        persisted_after_upload["youtube_video_id"]
        == "integration-test-video-id"
    )
    assert (
        persisted_after_upload["youtube_url"]
        == (
            "https://www.youtube.com/watch?v="
            "integration-test-video-id"
        )
    )

    assert publisher.uploaded_publications == [persisted]
