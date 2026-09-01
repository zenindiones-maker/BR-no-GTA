from typing import Any

from app.database.render_queue_repository import (
    get_render_job,
    update_render_job_status,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    NullRenderExecutor,
    RenderExecutionResult,
)


def execute_render_job(
    job_id: int,
    executor: AbstractRenderExecutor | None = None,
) -> RenderExecutionResult:
    """
    Orquestra a execução de um Render Job.

    Fluxo:

        queued
          ↓
        running
          ↓
      executor
       ↙     ↘
   completed  failed
    """

    render_job = get_render_job(job_id)

    if render_job is None:
        raise ValueError(f"Render job não encontrado: {job_id}")

    status = render_job.get("status")

    if status != "queued":
        raise ValueError(
            f"Render job {job_id} não está em estado queued: {status}"
        )

    selected_executor = executor or NullRenderExecutor()

    update_render_job_status(job_id, "running")

    try:
        result = selected_executor.execute(render_job)

        if not isinstance(result, RenderExecutionResult):
            raise TypeError(
                "O executor deve retornar RenderExecutionResult."
            )

        if result.success:
            update_render_job_status(job_id, "completed")
        else:
            update_render_job_status(job_id, "failed")

        return result

    except Exception as exc:
        update_render_job_status(job_id, "failed")

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error=str(exc),
        )


def execute_next_render_job(
    executor: AbstractRenderExecutor | None = None,
) -> RenderExecutionResult | None:
    """
    Executa o próximo Render Job disponível na fila.

    Retorna None quando não existe job queued.
    """

    from app.database.render_queue_repository import list_render_jobs

    jobs = list_render_jobs()

    queued_jobs = [
        job for job in jobs
        if job.get("status") == "queued"
    ]

    if not queued_jobs:
        return None

    job = queued_jobs[0]

    return execute_render_job(
        job["id"],
        executor=executor,
    )
