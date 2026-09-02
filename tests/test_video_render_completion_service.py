import pytest

from app.database.content_repository import insert_content_item
from app.database.render_queue_repository import (
    enqueue_render_job,
)
from app.database.video_repository import (
    get_video,
    insert_video,
)
from app.services.video_render_completion_service import (
    complete_video_from_render_job,
)


def _create_video() -> int:
    content_item_id = insert_content_item(
        title="Content Item para conclusão",
        content_type="short",
        status="ready",
    )

    return insert_video(
        content_item_id=content_item_id,
        title="Vídeo renderizado",
        status="draft",
    )


def _create_completed_render_job(
    video_id: int,
    output_path: str = "output/video.mp4",
) -> int:
    job = {
        "content_item_id": 1,
        "script_id": 10,
        "idea_id": 20,
        "objective": "Renderizar vídeo.",
        "format": "short",
        "estimated_duration_seconds": 30,
        "status": "completed",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 1,
        "video_id": video_id,
        "output_path": output_path,
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

    return enqueue_render_job(job)


def test_complete_video_from_render_job_updates_file_and_status():
    video_id = _create_video()

    render_job_id = _create_completed_render_job(
        video_id,
        "renders/final-video.mp4",
    )

    result = complete_video_from_render_job(
        render_job_id,
    )

    assert result["id"] == video_id
    assert result["file_path"] == "renders/final-video.mp4"
    assert result["status"] == "ready"

    persisted_video = get_video(video_id)

    assert persisted_video is not None
    assert persisted_video["file_path"] == (
        "renders/final-video.mp4"
    )
    assert persisted_video["status"] == "ready"


@pytest.mark.parametrize(
    "invalid_render_job_id",
    [
        None,
        0,
        -1,
        "1",
    ],
)
def test_complete_video_from_render_job_rejects_invalid_id(
    invalid_render_job_id,
):
    with pytest.raises(ValueError):
        complete_video_from_render_job(
            invalid_render_job_id,
        )


def test_complete_video_from_render_job_rejects_missing_job():
    with pytest.raises(ValueError, match="não encontrado"):
        complete_video_from_render_job(999999)


def test_complete_video_from_render_job_rejects_non_completed_job():
    video_id = _create_video()

    job = {
        "content_item_id": 1,
        "script_id": 10,
        "idea_id": 20,
        "objective": "Renderizar vídeo.",
        "format": "short",
        "estimated_duration_seconds": 30,
        "status": "queued",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
        "video_id": video_id,
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
        "render": {},
    }

    render_job_id = enqueue_render_job(job)

    with pytest.raises(ValueError, match="completed"):
        complete_video_from_render_job(
            render_job_id,
        )


def test_complete_video_from_render_job_requires_video_id():
    job = {
        "content_item_id": 1,
        "script_id": 10,
        "idea_id": 20,
        "objective": "Renderizar vídeo.",
        "format": "short",
        "estimated_duration_seconds": 30,
        "status": "completed",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 1,
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
        "render": {},
    }

    render_job_id = enqueue_render_job(job)

    with pytest.raises(ValueError, match="video_id"):
        complete_video_from_render_job(
            render_job_id,
        )


def test_complete_video_from_render_job_requires_output_path():
    video_id = _create_video()

    render_job_id = _create_completed_render_job(
        video_id,
        output_path="",
    )

    with pytest.raises(ValueError, match="output_path"):
        complete_video_from_render_job(
            render_job_id,
        )


def test_complete_video_from_render_job_requires_existing_video():
    render_job_id = _create_completed_render_job(
        999999,
        "renders/orphan.mp4",
    )

    with pytest.raises(ValueError, match="Video não encontrado"):
        complete_video_from_render_job(
            render_job_id,
        )
