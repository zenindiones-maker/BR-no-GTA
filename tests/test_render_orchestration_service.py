import pytest

from app.database.render_queue_repository import (
    enqueue_render_job,
    get_render_job,
)
from app.database.schema import initialize_schema
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    NullRenderExecutor,
    RenderExecutionResult,
)
from app.services.render_orchestration_service import execute_render_job


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


class SuccessfulExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        assert render_job["job_type"] == "video_render"
        return RenderExecutionResult(
            success=True,
            output_path="/tmp/rendered.mp4",
        )


class FailedExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        assert render_job["job_type"] == "video_render"
        return RenderExecutionResult(
            success=False,
            error="Falha simulada no executor.",
        )


def _enqueue_job():
    initialize_schema()
    return enqueue_render_job(_create_render_job())


def test_execute_render_job_success():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        SuccessfulExecutor(),
    )

    assert result.success is True
    assert result.output_path == "/tmp/rendered.mp4"

    stored = get_render_job(job_id)

    assert stored is not None
    assert stored["status"] == "completed"


def test_execute_render_job_failure_updates_status():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        FailedExecutor(),
    )

    assert result.success is False
    assert result.error == "Falha simulada no executor."

    stored = get_render_job(job_id)

    assert stored is not None
    assert stored["status"] == "failed"


def test_execute_render_job_with_null_executor():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        NullRenderExecutor(),
    )

    assert result.success is False

    stored = get_render_job(job_id)

    assert stored is not None
    assert stored["status"] == "failed"


def test_execute_render_job_rejects_missing_job():
    initialize_schema()

    with pytest.raises(ValueError, match="Render job não encontrado"):
        execute_render_job(
            999999,
            NullRenderExecutor(),
        )


def test_execute_render_job_rejects_invalid_executor():
    job_id = _enqueue_job()

    with pytest.raises(ValueError, match="executor"):
        execute_render_job(
            job_id,
            object(),
        )


def test_execute_render_job_rejects_non_queued_job():
    job_id = _enqueue_job()

    from app.database.render_queue_repository import update_render_job_status

    update_render_job_status(job_id, "running")

    with pytest.raises(ValueError, match="queued"):
        execute_render_job(
            job_id,
            NullRenderExecutor(),
        )


def test_execute_render_job_does_not_depend_on_ffmpeg():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        SuccessfulExecutor(),
    )

    assert result.success is True
    assert result.output_path == "/tmp/rendered.mp4"


def test_executor_contract_is_preserved():
    executor = SuccessfulExecutor()

    assert isinstance(
        executor,
        AbstractRenderExecutor,
    )
