import pytest

from app.database.content_repository import insert_content_item
from app.database.schema import initialize_schema
from app.database.video_repository import mark_video_ready
from app.database.youtube_repository import (
    get_youtube_publication,
)
from app.services.video_service import create_video
from app.services.youtube_publication_service import (
    create_youtube_publication,
)
from app.services.youtube_publication_orchestration import (
    publish_youtube_publication,
)
from app.services.fake_youtube_publisher import (
    FakeYouTubePublisher,
)


@pytest.fixture(autouse=True)
def setup_database():
    initialize_schema()


def create_ready_video():
    content_item_id = insert_content_item(
        title="Content Item para publicação",
        content_type="video",
        status="ready",
    )

    video = create_video(
        {
            "content_item_id": content_item_id,
            "script_id": 10,
            "idea_id": 20,
            "objective": "Gerar vídeo para publicação.",
            "format": "short",
            "estimated_duration_seconds": 45,
            "scenes": [
                {
                    "order": 1,
                    "narrative_block": "Abertura",
                    "narration": "Introdução.",
                    "visual_type": "gameplay",
                    "visual_description": "Gameplay de GTA.",
                    "duration_seconds": 5,
                    "requirements": [],
                }
            ],
            "audio_requirements": [],
            "visual_requirements": [],
        }
    )

    assert video["status"] == "draft"

    ready = mark_video_ready(
        video_id=video["id"],
        file_path="output/youtube.mp4",
    )

    assert ready is True

    return {
        **video,
        "status": "ready",
        "file_path": "output/youtube.mp4",
    }


def test_publish_youtube_publication_success():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    assert publication["status"] == "pending"

    publisher = FakeYouTubePublisher(
        success=True,
        youtube_video_id="youtube-test-123",
        youtube_url="https://www.youtube.com/watch?v=youtube-test-123",
    )

    result = publish_youtube_publication(
        publication_id=publication["id"],
        publisher=publisher,
    )

    assert result["id"] == publication["id"]
    assert result["status"] == "published"
    assert result["youtube_video_id"] == "youtube-test-123"
    assert (
        result["youtube_url"]
        == "https://www.youtube.com/watch?v=youtube-test-123"
    )
    assert result["error"] is None
    assert publisher.published_publication == publication


def test_publish_youtube_publication_failure():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    publisher = FakeYouTubePublisher(
        success=False,
        error="Falha simulada no Publisher.",
    )

    result = publish_youtube_publication(
        publication_id=publication["id"],
        publisher=publisher,
    )

    assert result["id"] == publication["id"]
    assert result["status"] == "failed"
    assert result["youtube_video_id"] is None
    assert result["youtube_url"] is None
    assert result["error"] == "Falha simulada no Publisher."


def test_publish_youtube_publication_does_not_call_google():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    publisher = FakeYouTubePublisher(
        success=True,
        youtube_video_id="fake-google-free-id",
        youtube_url="https://www.youtube.com/watch?v=fake-google-free-id",
    )

    result = publish_youtube_publication(
        publication_id=publication["id"],
        publisher=publisher,
    )

    persisted = get_youtube_publication(publication["id"])

    assert result["status"] == "published"
    assert persisted["status"] == "published"
    assert publisher.published_publication["id"] == publication["id"]


def test_publish_youtube_publication_requires_pending_status():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    publisher = FakeYouTubePublisher(
        success=True,
        youtube_video_id="youtube-test-456",
        youtube_url="https://www.youtube.com/watch?v=youtube-test-456",
    )

    first_result = publish_youtube_publication(
        publication_id=publication["id"],
        publisher=publisher,
    )

    assert first_result["status"] == "published"

    with pytest.raises(ValueError, match="pending"):
        publish_youtube_publication(
            publication_id=publication["id"],
            publisher=publisher,
        )


def test_publish_youtube_publication_requires_publisher_result():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    class InvalidPublisher:
        def publish(self, publication):
            return {"status": "published"}

    with pytest.raises(TypeError, match="YouTubePublishResult"):
        publish_youtube_publication(
            publication_id=publication["id"],
            publisher=InvalidPublisher(),
        )
