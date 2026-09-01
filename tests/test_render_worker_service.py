import pytest

from app.database.schema import initialize_schema
from app.database.render_queue_repository import (
    enqueue_render_job,
    get_render_job,
)
from app.services.render_worker_service import (
    process_next_render_job,
)


def _create_job():
    initialize_schema()

    return {
        "content_item_id": 1,
        "script_id": 2,
        "idea_id": 3,
        "objective": "Gerar vídeo editorial",
        "format": "short",
        "estimated_duration_seconds": 60,
        "status": "queued",
        "scenes": [
            {
                "order": 1,
                "narrative_block": "Abertura",
                "narration": "Texto inicial",
                "visual_type": "b-roll",
                "visual_description": "Cena de abertura",
                "duration_seconds": 10,
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
        "job_type": "video_render",
        "queue": "render",
        "attempt": 0,
    }


def test_process_next_render_job_returns_job():
    job_id = enqueue_render_job(_create_job())

    result = process_next_render_job()

    assert result is not None
    assert result["id"] == job_id


def test_process_next_render_job_changes_status_to_running():
    job_id = enqueue_render_job(_create_job())

    result = process_next_render_job()

    assert result["id"] == job_id
    assert result["status"] == "running"


def test_process_next_render_job_preserves_render_payload():
    job_id = enqueue_render_job(_create_job())

    result = process_next_render_job()

    assert result["render"]["resolution"] == "1920x1080"
    assert result["render"]["fps"] == 30
    assert result["render"]["video_codec"] == "h264"
    assert result["render"]["audio_codec"] == "aac"
    assert result["scenes"]


def test_process_next_render_job_preserves_job_identity():
    job = _create_job()
    job_id = enqueue_render_job(job)

    result = process_next_render_job()

    assert result["id"] == job_id
    assert result["content_item_id"] == job["content_item_id"]
    assert result["script_id"] == job["script_id"]
    assert result["idea_id"] == job["idea_id"]


def test_process_next_render_job_returns_none_when_queue_is_empty():
    initialize_schema()

    result = process_next_render_job()

    assert result is None


def test_process_next_render_job_rejects_invalid_queue_state():
    initialize_schema()

    with pytest.raises(ValueError, match="render job"):
        process_next_render_job({})
