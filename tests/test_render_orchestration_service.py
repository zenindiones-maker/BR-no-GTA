import pytest
from app.database.video_repository import get_video

from app.database.schema import initialize_schema
from app.database.ideas_repository import insert_idea
from app.database.render_queue_repository import (
    get_render_job,
    transition_render_job,
    claim_next_render_job,
)
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.video_service import create_video_spec
from app.services.video_execution_service import create_video_execution_spec
from app.services.render_job_service import create_render_job
from app.services.render_queue_service import enqueue_video_render
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)
from app.services.render_orchestration_service import (
    execute_render_job,
    execute_next_render_job,
)


class SuccessfulExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        assert render_job["status"] == "running"

        return RenderExecutionResult(
            success=True,
            output_path="/tmp/rendered-video.mp4",
        )


class FailedExecutor(AbstractRenderExecutor):
    def execute(self, render_job):
        assert render_job["status"] == "running"

        return RenderExecutionResult(
            success=False,
            error="Falha simulada no executor.",
        )


def _enqueue_job():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - render orchestration",
        description="Pauta aprovada para testar a orquestração.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)
    item = create_content_item(spec)
    plan = create_production_plan(item)
    video = create_video_spec(plan)
    execution = create_video_execution_spec(video)

    return enqueue_video_render(execution)


def test_execute_render_job_success_transitions_to_completed():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        executor=SuccessfulExecutor(),
    )

    assert result.success is True
    assert result.output_path == "/tmp/rendered-video.mp4"

    job = get_render_job(job_id)

    assert job["status"] == "completed"
    assert job["output_path"] == "/tmp/rendered-video.mp4"
    assert job["error"] is None
    assert job["attempt"] == 1


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
    assert job["error"] == "Falha simulada no executor."
    assert job["output_path"] is None
    assert job["attempt"] == 1


def test_execute_render_job_requires_queued_state():
    job_id = _enqueue_job()

    with pytest.raises(ValueError, match="Transição inválida"):
        transition_render_job(job_id, "completed")


def test_execute_render_job_rejects_completed_job():
    job_id = _enqueue_job()

    transition_render_job(job_id, "running")
    transition_render_job(
        job_id,
        "completed",
        output_path="/tmp/video.mp4",
    )

    with pytest.raises(ValueError, match="queued"):
        execute_render_job(
            job_id,
            executor=SuccessfulExecutor(),
        )


def test_execute_render_job_rejects_failed_job():
    job_id = _enqueue_job()

    transition_render_job(job_id, "running")
    transition_render_job(
        job_id,
        "failed",
        error="Falha anterior.",
    )

    with pytest.raises(ValueError):
        execute_render_job(
            job_id,
            executor=SuccessfulExecutor(),
        )


def test_execute_next_render_job_processes_first_queued_job():
    job_id = _enqueue_job()

    result = execute_next_render_job(
        executor=SuccessfulExecutor(),
    )

    assert result.success is True
    assert result.output_path == "/tmp/rendered-video.mp4"

    job = get_render_job(job_id)

    assert job["status"] == "completed"
    assert job["attempt"] == 1


def test_orchestration_persists_attempt_and_output_path():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        executor=SuccessfulExecutor(),
    )

    assert result.success is True

    job = get_render_job(job_id)

    assert job["attempt"] == 1
    assert job["output_path"] == "/tmp/rendered-video.mp4"


def test_orchestration_persists_attempt_and_error():
    job_id = _enqueue_job()

    result = execute_render_job(
        job_id,
        executor=FailedExecutor(),
    )

    assert result.success is False

    job = get_render_job(job_id)

    assert job["status"] == "failed"
    assert job["attempt"] == 1
    assert job["error"] == "Falha simulada no executor."


def test_orchestration_does_not_increment_attempt_when_not_queued():
    job_id = _enqueue_job()

    transition_render_job(job_id, "running")

    job_before = get_render_job(job_id)

    assert job_before["attempt"] == 1

    with pytest.raises(ValueError):
        execute_render_job(
            job_id,
            executor=SuccessfulExecutor(),
        )

    job_after = get_render_job(job_id)

    assert job_after["status"] == "running"
    assert job_after["attempt"] == 1

def test_execute_render_job_success_completes_associated_video():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - fechamento Render -> Video",
        description="Pauta aprovada para testar o fechamento do ciclo.",
        status="approved",
        score=9.5,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)
    item = create_content_item(spec)
    plan = create_production_plan(item)
    video_spec = create_video_spec(plan)

    from app.services.video_service import create_video

    video = create_video(video_spec)
    video_id = video["id"]

    execution = create_video_execution_spec(video)
    job_id = enqueue_video_render(execution, video_id=video_id)

    result = execute_render_job(
        job_id,
        executor=SuccessfulExecutor(),
    )

    assert result.success is True
    assert result.output_path == "/tmp/rendered-video.mp4"

    job = get_render_job(job_id)

    assert job is not None
    assert job["status"] == "completed"
    assert job["video_id"] == video_id
    assert job["output_path"] == "/tmp/rendered-video.mp4"

    persisted_video = get_video(video_id)

    assert persisted_video is not None
    assert persisted_video["status"] == "ready"
    assert persisted_video["file_path"] == "/tmp/rendered-video.mp4"
