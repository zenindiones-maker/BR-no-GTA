from typing import Any

from app.database.render_queue_repository import (
    get_render_job,
    update_render_job_status,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    RenderExecutionResult,
)


def execute_render_job(
    job_id: int,
    executor: AbstractRenderExecutor,
) -> RenderExecutionResult:
    """
    Orquestra a execução de um Render Job.

    Fluxo:
        Render Queue
            ↓
        Render Worker / Orchestrator
            ↓
        Render Executor
            ↓
        RenderExecutionResult
            ↓
        atualização do status

    Esta camada não conhece nem depende de FFmpeg.
    """

    if not isinstance(executor, AbstractRenderExecutor):
        raise ValueError("O executor de renderização informado é inválido.")

    render_job = get_render_job(job_id)

    if render_job is None:
        raise ValueError(f"Render job não encontrado: {job_id}.")

    if render_job.get("status") != "queued":
        raise ValueError(
            f"O render job precisa estar em estado queued para execução: "
            f"{render_job.get('status')}."
        )

    update_render_job_status(job_id, "running")

    try:
        result = executor.execute(render_job)

        if not isinstance(result, RenderExecutionResult):
            raise ValueError(
                "O executor de renderização retornou um resultado inválido."
            )

        if result.success:
            update_render_job_status(job_id, "completed")
        else:
            update_render_job_status(job_id, "failed")

        return result

    except Exception:
        update_render_job_status(job_id, "failed")
        raise
