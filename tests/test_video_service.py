import pytest

from app.database.content_repository import insert_content_item
from app.database.video_repository import get_video
from app.services.video_service import create_video


def _create_video_spec(content_item_id: int) -> dict:
    return {
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
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
    }


def test_create_video_persists_video():
    content_item_id = insert_content_item(
        title="Content Item para vídeo",
        content_type="short",
        status="ready",
    )

    video_spec = _create_video_spec(content_item_id)

    video = create_video(video_spec)

    assert video["id"] > 0
    assert video["content_item_id"] == content_item_id
    assert video["status"] == "draft"
    assert video["scenes"]

    persisted = get_video(video["id"])

    assert persisted is not None
    assert persisted["id"] == video["id"]
    assert persisted["content_item_id"] == content_item_id
    assert persisted["title"] == video["title"]
    assert persisted["status"] == "draft"


@pytest.mark.parametrize(
    "missing_field",
    [
        "content_item_id",
        "script_id",
        "idea_id",
        "objective",
        "format",
        "estimated_duration_seconds",
        "scenes",
        "audio_requirements",
        "visual_requirements",
    ],
)
def test_create_video_requires_fields(missing_field):
    content_item_id = insert_content_item(
        title="Content Item",
        content_type="short",
        status="ready",
    )

    video_spec = _create_video_spec(content_item_id)
    del video_spec[missing_field]

    with pytest.raises(ValueError):
        create_video(video_spec)


def test_create_video_requires_scenes():
    content_item_id = insert_content_item(
        title="Content Item",
        content_type="short",
        status="ready",
    )

    video_spec = _create_video_spec(content_item_id)
    video_spec["scenes"] = []

    with pytest.raises(ValueError):
        create_video(video_spec)
