from app.database.render_queue_repository import (
    get_render_job,
    list_render_jobs,
    transition_render_job,
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

    O job só pode ser executado quando estiver em `queued`.

    Fluxo:

        queued
          ↓
        running
          ↓
       executor
        ↙    ↘
    completed failed
    """

    render_job = get_render_job(job_id)

    if render_job is None:
        raise ValueError(
            f"Render job não encontrado: {job_id}"
        )

    current_status = render_job.get("status")

    if current_status != "queued":
        raise ValueError(
            f"Render job {job_id} não está em estado queued: "
            f"{current_status}"
        )

    selected_executor = executor or NullRenderExecutor()

    running_job = transition_render_job(
        job_id,
        "running",
    )

    try:
        result = selected_executor.execute(running_job)

        if not isinstance(result, RenderExecutionResult):
            raise TypeError(
                "O executor deve retornar RenderExecutionResult."
            )

        if result.success:
            if not result.output_path:
                raise ValueError(
                    "RenderExecutionResult de sucesso precisa possuir "
                    "output_path."
                )

            transition_render_job(
                job_id,
                "completed",
                output_path=result.output_path,
            )

        else:
            if not result.error:
                raise ValueError(
                    "RenderExecutionResult de falha precisa possuir error."
                )

            transition_render_job(
                job_id,
                "failed",
                error=result.error,
            )

        return result

    except Exception as exc:
        error = str(exc)

        try:
            transition_render_job(
                job_id,
                "failed",
                error=error,
            )
        except ValueError:
            pass

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error=error,
        )


def execute_next_render_job(
    executor: AbstractRenderExecutor | None = None,
) -> RenderExecutionResult | None:
    """
    Executa exatamente um Render Job queued.

    O orquestrador:
    1. consulta os jobs persistidos;
    2. seleciona o primeiro job queued;
    3. delega a execução para execute_render_job().

    Jobs completed/failed/cancelled nunca são selecionados.
    """

    jobs = list_render_jobs()

    for job in jobs:
        if job.get("status") != "queued":
            continue

        job_id = job.get("id")

        if job_id is None:
            raise ValueError(
                "Render Job queued não possui id persistido."
            )

        return execute_render_job(
            int(job_id),
            executor=executor,
        )

    return None
