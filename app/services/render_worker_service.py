from app.database.render_queue_repository import get_render_job
from app.services.audiovisual_executor_factory import (
    create_audiovisual_executor,
)
from app.services.render_executor_service import AbstractRenderExecutor
from app.services.render_orchestration_service import (
    execute_next_render_job,
    execute_render_job,
    reconcile_running_cloud_render_job_metadata,
)


def process_render_job(
    job_id: int,
    executor: AbstractRenderExecutor | None = None,
    execution_context: dict | None = None,
):
    """Process or reconcile exactly one explicitly targeted RenderJob."""
    selected_executor = executor
    if selected_executor is None:
        selected_executor = create_audiovisual_executor()

    job = get_render_job(job_id)
    if job is None:
        raise ValueError(f"Render job não encontrado: {job_id}")

    if job.get("status") == "running":
        if not job.get("github_execution"):
            raise ValueError(
                f"Render job {job_id} is running without persisted github_execution"
            )
        if selected_executor is None:
            raise RuntimeError("GitHub Actions audiovisual executor is not configured")
        return reconcile_running_cloud_render_job_metadata(
            job_id,
            selected_executor,
            execution_context=execution_context,
        )

    if execution_context is None:
        return execute_render_job(
            job_id,
            executor=selected_executor,
        )
    return execute_render_job(
        job_id,
        executor=selected_executor,
        execution_context=execution_context,
    )


def process_next_render_job(
    executor: AbstractRenderExecutor | None = None,
    execution_context: dict | None = None,
):
    """Process exactly one legacy untargeted queued RenderJob."""
    selected_executor = executor
    if selected_executor is None:
        selected_executor = create_audiovisual_executor()
    if execution_context is None:
        return execute_next_render_job(
            executor=selected_executor,
        )
    return execute_next_render_job(
        executor=selected_executor,
        execution_context=execution_context,
    )
