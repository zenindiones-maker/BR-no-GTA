import pytest

from app.database.schema import initialize_schema
from app.database.ideas_repository import insert_idea
from app.database.render_queue_repository import (
    get_render_job,
    list_render_jobs,
)
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.video_service import create_video_spec
from app.services.video_execution_service import create_video_execution_spec
from app.services.render_job_service import create_render_job
from app.services.render_queue_service import enqueue_video_render
from app.services.render_orchestration_service import execute_render_job
from app.services.fake_render_executor_service import FakeRenderExecutor


def _create_queued_render_job():
    initialize_schema()

    idea_id = insert_idea(
        title="TESTE - pipeline completa",
        description="Teste determinístico da pipeline de renderização.",
        status="approved",
        score=10.0,
    )

    script_id = generate_and_save_script(idea_id)
    spec = generate_script_spec(script_id)
    item = create_content_item(spec)
    plan = create_production_plan(item)
    video = create_video_spec(plan)
    execution = create_video_execution_spec(video)

    render_job = create_render_job(execution)

    return enqueue_video_render(render_job)


def test_fake_executor_success_completes_pipeline():
    job_id = _create_queued_render_job()

    result = execute_render_job(
        job_id,
        executor=FakeRenderExecutor(success=True),
    )

    assert result.success is True
    assert result.output_path is not None
    assert result.error is None

    job = get_render_job(job_id)

    assert job["status"] == "completed"
    assert job["attempt"] == 1
    assert job["output_path"] == result.output_path
    assert job["error"] is None


def test_fake_executor_failure_fails_pipeline():
    job_id = _create_queued_render_job()

    result = execute_render_job(
        job_id,
        executor=FakeRenderExecutor(success=False),
    )

    assert result.success is False
    assert result.error is not None

    job = get_render_job(job_id)

    assert job["status"] == "failed"
    assert job["attempt"] == 1
    assert job["error"] == result.error
    assert job["output_path"] is None


def test_fake_executor_success_does_not_leave_running_job():
    job_id = _create_queued_render_job()

    execute_render_job(
        job_id,
        executor=FakeRenderExecutor(success=True),
    )

    job = get_render_job(job_id)

    assert job["status"] == "completed"
    assert job["status"] != "running"


def test_fake_executor_failure_does_not_leave_running_job():
    job_id = _create_queued_render_job()

    execute_render_job(
        job_id,
        executor=FakeRenderExecutor(success=False),
    )

    job = get_render_job(job_id)

    assert job["status"] == "failed"
    assert job["status"] != "running"


def test_successful_pipeline_increments_attempt_once():
    job_id = _create_queued_render_job()

    execute_render_job(
        job_id,
        executor=FakeRenderExecutor(success=True),
    )

    job = get_render_job(job_id)

    assert job["attempt"] == 1


def test_failed_pipeline_increments_attempt_once():
    job_id = _create_queued_render_job()

    execute_render_job(
        job_id,
        executor=FakeRenderExecutor(success=False),
    )

    job = get_render_job(job_id)

    assert job["attempt"] == 1


def test_completed_job_cannot_be_executed_again():
    job_id = _create_queued_render_job()

    first_result = execute_render_job(
        job_id,
        executor=FakeRenderExecutor(success=True),
    )

    assert first_result.success is True

    with pytest.raises(ValueError, match="queued"):
        execute_render_job(
            job_id,
            executor=FakeRenderExecutor(success=True),
        )

def test_failed_job_cannot_be_reexecuted_without_requeue():
    job_id = _create_queued_render_job()

    first_result = execute_render_job(
        job_id,
        executor=FakeRenderExecutor(success=False),
    )

    assert first_result.success is False

    with pytest.raises(ValueError, match="queued"):
        execute_render_job(
            job_id,
            executor=FakeRenderExecutor(success=True),
        )
