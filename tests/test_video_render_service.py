import pytest

from app.database.content_repository import insert_content_item
from app.database.render_queue_repository import get_render_job
from app.database.video_repository import get_video
from app.services.video_render_service import (
    create_video_and_enqueue_render,
)


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


def test_create_video_and_enqueue_render_composes_video_and_job():
    content_item_id = insert_content_item(
        title="Content Item para render",
        content_type="short",
        status="ready",
    )

    video_spec = _create_video_spec(content_item_id)

    result = create_video_and_enqueue_render(
        video_spec,
    )

    assert isinstance(result, dict)
    assert "video" in result
    assert "render_job" in result

    video = result["video"]
    render_job = result["render_job"]

    assert video["id"] > 0
    assert video["content_item_id"] == content_item_id
    assert video["status"] == "draft"

    assert render_job["id"] > 0
    assert render_job["video_id"] == video["id"]
    assert render_job["status"] == "queued"

    persisted_video = get_video(video["id"])

    assert persisted_video is not None
    assert persisted_video["id"] == video["id"]

    persisted_render_job = get_render_job(
        render_job["id"],
    )

    assert persisted_render_job is not None
    assert persisted_render_job["video_id"] == video["id"]


def test_create_video_and_enqueue_render_does_not_add_video_id_to_execution_spec(
    monkeypatch,
):
    content_item_id = insert_content_item(
        title="Content Item para execução",
        content_type="short",
        status="ready",
    )

    video_spec = _create_video_spec(content_item_id)

    captured = {}

    def fake_create_video_execution_spec(spec):
        captured["spec"] = spec

        return {
            "content_item_id": spec["content_item_id"],
            "script_id": spec["script_id"],
            "idea_id": spec["idea_id"],
            "objective": spec["objective"],
            "format": spec["format"],
            "estimated_duration_seconds": (
                spec["estimated_duration_seconds"]
            ),
            "status": "ready",
            "scenes": [
                {
                    "order": 1,
                    "narrative_block": "Abertura",
                    "narration": "Introdução.",
                    "visual_type": "gameplay",
                    "visual_description": "Gameplay de GTA.",
                    "duration_seconds": 5,
                    "execution_requirements": [],
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

    monkeypatch.setattr(
        "app.services.video_render_service.create_video_execution_spec",
        fake_create_video_execution_spec,
    )

    result = create_video_and_enqueue_render(
        video_spec,
    )

    assert result["render_job"]["video_id"] == result["video"]["id"]
    assert "video_id" not in captured["spec"]


@pytest.mark.parametrize(
    "invalid_video_spec",
    [
        None,
        {},
        [],
        "video",
    ],
)
def test_create_video_and_enqueue_render_rejects_invalid_video_spec(
    invalid_video_spec,
):
    with pytest.raises(ValueError):
        create_video_and_enqueue_render(
            invalid_video_spec,
        )
