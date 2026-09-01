import pytest

from app.database.render_queue_repository import get_render_job
from app.services.fake_render_executor_service import FakeRenderExecutor
from app.services.render_worker_service import process_next_render_job


def _create_queued_render_job():
    from app.database.render_queue_repository import enqueue_render_job
    from app.services.render_job_service import create_render_job

    job = create_render_job(
        {
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
    )

    return enqueue_render_job(job)


def test_worker_executes_queued_job_through_orchestrator():
    job_id = _create_queued_render_job()

    result = process_next_render_job(
        executor=FakeRenderExecutor(
            success=True,
            output_path="/tmp/fake-render.mp4",
        )
    )

    assert result.success is True
    assert result.output_path == "/tmp/fake-render.mp4"

    job = get_render_job(job_id)

    assert job["status"] == "completed"
    assert job["attempt"] == 1
    assert job["output_path"] == "/tmp/fake-render.mp4"
    assert job["error"] is None


def test_worker_executes_failure_through_orchestrator():
    job_id = _create_queued_render_job()

    result = process_next_render_job(
        executor=FakeRenderExecutor(
            success=False,
            error="Falha simulada no render.",
        )
    )

    assert result.success is False
    assert result.error == "Falha simulada no render."

    job = get_render_job(job_id)

    assert job["status"] == "failed"
    assert job["attempt"] == 1
    assert job["output_path"] is None
    assert job["error"] == "Falha simulada no render."


def test_worker_does_not_execute_terminal_job_again():
    job_id = _create_queued_render_job()

    first_result = process_next_render_job(
        executor=FakeRenderExecutor(
            success=True,
            output_path="/tmp/fake-render.mp4",
        )
    )

    assert first_result.success is True

    second_result = process_next_render_job(
        executor=FakeRenderExecutor(
            success=True,
            output_path="/tmp/second-render.mp4",
        )
    )

    assert second_result is None

    job = get_render_job(job_id)

    assert job["status"] == "completed"
    assert job["attempt"] == 1
    assert job["output_path"] == "/tmp/fake-render.mp4"
