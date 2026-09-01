import pytest

from app.database.schema import initialize_schema
from app.database.render_queue_repository import (
    enqueue_render_job,
    get_render_job,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)
from app.services.render_worker_service import (
    process_next_render_job,
)


class SuccessfulExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        assert render_job["status"] == "running"

        return RenderExecutionResult(
            success=True,
            output_path="/tmp/worker-video.mp4",
        )


class FailedExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        assert render_job["status"] == "running"

        return RenderExecutionResult(
            success=False,
            error="Falha simulada no worker.",
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


def test_process_next_render_job_returns_execution_result():
    job_id = enqueue_render_job(
        _create_job()
    )

    result = process_next_render_job(
        executor=SuccessfulExecutor()
    )

    assert result is not None
    assert result.success is True
    assert result.output_path == "/tmp/worker-video.mp4"

    job = get_render_job(job_id)

    assert job["id"] == job_id
    assert job["status"] == "completed"


def test_process_next_render_job_transitions_queued_to_completed():
    job_id = enqueue_render_job(
        _create_job()
    )

    result = process_next_render_job(
        executor=SuccessfulExecutor()
    )

    assert result.success is True

    job = get_render_job(job_id)

    assert job["status"] == "completed"
    assert job["attempt"] == 1
    assert job["output_path"] == "/tmp/worker-video.mp4"
    assert job["error"] is None


def test_process_next_render_job_preserves_render_payload():
    job_id = enqueue_render_job(
        _create_job()
    )

    result = process_next_render_job(
        executor=SuccessfulExecutor()
    )

    assert result.success is True

    job = get_render_job(job_id)

    assert job["render"]["resolution"] == "1920x1080"
    assert job["render"]["fps"] == 30
    assert job["render"]["video_codec"] == "h264"
    assert job["render"]["audio_codec"] == "aac"
    assert job["scenes"]


def test_process_next_render_job_preserves_job_identity():
    original_job = _create_job()

    job_id = enqueue_render_job(
        original_job
    )

    result = process_next_render_job(
        executor=SuccessfulExecutor()
    )

    assert result.success is True

    job = get_render_job(job_id)

    assert job["id"] == job_id
    assert job["content_item_id"] == original_job["content_item_id"]
    assert job["script_id"] == original_job["script_id"]
    assert job["idea_id"] == original_job["idea_id"]


def test_process_next_render_job_returns_none_when_queue_is_empty():
    initialize_schema()

    result = process_next_render_job(
        executor=SuccessfulExecutor()
    )

    assert result is None


def test_process_next_render_job_failure_persists_failed_job():
    job_id = enqueue_render_job(
        _create_job()
    )

    result = process_next_render_job(
        executor=FailedExecutor()
    )

    assert result is not None
    assert result.success is False
    assert result.error == "Falha simulada no worker."

    job = get_render_job(job_id)

    assert job["status"] == "failed"
    assert job["attempt"] == 1
    assert job["error"] == "Falha simulada no worker."
    assert job["output_path"] is None
