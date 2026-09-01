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
from app.services.render_orchestration_service import (
    execute_render_job,
    execute_next_render_job,
)


def _create_render_job():
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


def _enqueue_job():
    initialize_schema()
    return enqueue_render_job(_create_render_job())


class SuccessfulExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        assert render_job["status"] == "queued"

        return RenderExecutionResult(
            success=True,
            output_path="/renders/video-001.mp4",
        )


class FailedExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        assert render_job["status"] == "queued"

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error="Falha simulada no executor.",
        )


class ExceptionExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        raise RuntimeError("Erro interno simulado.")


class InvalidResultExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        return {"success": True}


def test_execute_render_job_success_transitions_to_completed():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        executor=SuccessfulExecutor(),
    )

    assert result.success is True
    assert result.output_path == "/renders/video-001.mp4"

    job = get_render_job(job_id)

    assert job["status"] == "completed"


def test_execute_render_job_failure_transitions_to_failed():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        executor=FailedExecutor(),
    )

    assert result.success is False
    assert result.error == "Falha simulada no executor."

    job = get_render_job(job_id)

    assert job["status"] == "failed"


def test_execute_render_job_executor_exception_transitions_to_failed():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        executor=ExceptionExecutor(),
    )

    assert result.success is False
    assert result.error == "Erro interno simulado."

    job = get_render_job(job_id)

    assert job["status"] == "failed"


def test_execute_render_job_requires_queued_state():
    job_id = _enqueue_job()

    from app.database.render_queue_repository import (
        update_render_job_status,
    )

    update_render_job_status(job_id, "completed")

    with pytest.raises(ValueError, match="queued"):
        execute_render_job(
            job_id,
            executor=SuccessfulExecutor(),
        )


def test_execute_render_job_rejects_missing_job():
    initialize_schema()

    with pytest.raises(ValueError, match="não encontrado"):
        execute_render_job(
            999999,
            executor=SuccessfulExecutor(),
        )


def test_execute_render_job_rejects_invalid_executor_result():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        executor=InvalidResultExecutor(),
    )

    assert result.success is False
    assert "RenderExecutionResult" in result.error

    job = get_render_job(job_id)

    assert job["status"] == "failed"


def test_execute_next_render_job_processes_first_queued_job():
    job_id = _enqueue_job()

    result = execute_next_render_job(
        executor=SuccessfulExecutor(),
    )

    assert result.success is True
    assert result.output_path == "/renders/video-001.mp4"

    job = get_render_job(job_id)

    assert job["status"] == "completed"


def test_execute_next_render_job_returns_none_when_queue_is_empty():
    initialize_schema()

    result = execute_next_render_job(
        executor=SuccessfulExecutor(),
    )

    assert result is None
