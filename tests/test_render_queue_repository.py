import pytest

from app.database.schema import initialize_schema
from app.database.render_queue_repository import (
    enqueue_render_job,
    get_render_job,
    list_render_jobs,
    update_render_job_status,
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


def test_enqueue_render_job():
    job = _create_job()

    job_id = enqueue_render_job(job)

    assert job_id > 0


def test_get_render_job():
    job = _create_job()

    job_id = enqueue_render_job(job)
    stored = get_render_job(job_id)

    assert stored is not None
    assert stored["id"] == job_id
    assert stored["content_item_id"] == job["content_item_id"]
    assert stored["status"] == "queued"


def test_list_render_jobs():
    job = _create_job()

    enqueue_render_job(job)
    enqueue_render_job(job)

    jobs = list_render_jobs()

    assert len(jobs) >= 2
    assert all(item["job_type"] == "video_render" for item in jobs)


def test_update_render_job_status():
    job = _create_job()

    job_id = enqueue_render_job(job)

    updated = update_render_job_status(job_id, "running")

    assert updated is True

    stored = get_render_job(job_id)

    assert stored["status"] == "running"


def test_render_job_preserves_payload():
    job = _create_job()

    job_id = enqueue_render_job(job)
    stored = get_render_job(job_id)

    assert stored["scenes"]
    assert stored["render"]["resolution"] == "1920x1080"
    assert stored["render"]["fps"] == 30
    assert stored["render"]["video_codec"] == "h264"


def test_render_job_rejects_invalid_job():
    initialize_schema()

    with pytest.raises(ValueError, match="render job"):
        enqueue_render_job({})


def test_render_job_rejects_invalid_status():
    job = _create_job()

    job_id = enqueue_render_job(job)

    with pytest.raises(ValueError, match="status"):
        update_render_job_status(job_id, "invalid_status")
