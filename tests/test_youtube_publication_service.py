import pytest

from app.database.content_repository import insert_content_item
from app.database.schema import initialize_schema
from app.database.youtube_repository import (
    get_youtube_publication_by_video_id,
)
from app.database.video_repository import mark_video_ready
from app.services.video_service import create_video
from app.services.youtube_publication_service import (
    create_youtube_publication,
)


@pytest.fixture(autouse=True)
def setup_database():
    initialize_schema()


def create_ready_video():
    content_item_id = insert_content_item(
        title="Content Item para YouTube",
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


def test_create_youtube_publication_persists_pending_publication():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    assert publication["id"] > 0
    assert publication["video_id"] == video["id"]
    assert publication["content_item_id"] == video["content_item_id"]
    assert publication["title"] == video["title"]
    assert publication["status"] == "pending"
    assert publication["youtube_video_id"] is None
    assert publication["youtube_url"] is None
    assert publication["error"] is None


def test_create_youtube_publication_persists_metadata():
    video = create_ready_video()

    video["description"] = "Descrição do vídeo"
    video["tags"] = [
        "GTA 6",
        "GTA",
        "Rockstar",
    ]
    video["category_id"] = "20"
    video["privacy_status"] = "public"

    publication = create_youtube_publication(video)

    assert publication["description"] == "Descrição do vídeo"
    assert publication["tags"] == [
        "GTA 6",
        "GTA",
        "Rockstar",
    ]
    assert publication["category_id"] == "20"
    assert publication["privacy_status"] == "public"


def test_create_youtube_publication_defaults_privacy_to_private():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    assert publication["privacy_status"] == "private"


def test_create_youtube_publication_requires_ready_video():
    video = create_ready_video()
    video["status"] = "draft"

    with pytest.raises(ValueError):
        create_youtube_publication(video)


def test_create_youtube_publication_rejects_duplicate_video():
    video = create_ready_video()

    first = create_youtube_publication(video)

    assert first["status"] == "pending"

    with pytest.raises(ValueError):
        create_youtube_publication(video)


def test_create_youtube_publication_can_be_retrieved_by_video_id():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    persisted = get_youtube_publication_by_video_id(
        video["id"]
    )

    assert persisted is not None
    assert persisted["id"] == publication["id"]
    assert persisted["video_id"] == video["id"]
    assert persisted["status"] == "pending"


def test_create_youtube_publication_does_not_publish():
    video = create_ready_video()

    publication = create_youtube_publication(video)

    assert publication["status"] == "pending"
    assert publication["youtube_video_id"] is None
    assert publication["youtube_url"] is None
    assert publication["error"] is None
