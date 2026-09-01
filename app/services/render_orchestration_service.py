from app.database.render_queue_repository import (
    claim_next_render_job,
    get_render_job,
    transition_render_job,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    NullRenderExecutor,
    RenderExecutionResult,
)


def _execute_running_render_job(
    running_job: dict,
    executor: AbstractRenderExecutor | None = None,
) -> RenderExecutionResult:
    """Executa um Render Job que já foi reservado como running."""

    job_id = running_job.get("id")

    if job_id is None:
        raise ValueError(
            "Render Job running não possui id persistido."
        )

    selected_executor = executor or NullRenderExecutor()

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
                int(job_id),
                "completed",
                output_path=result.output_path,
            )

            return result

        if not result.error:
            raise ValueError(
                "RenderExecutionResult de falha precisa possuir error."
            )

        transition_render_job(
            int(job_id),
            "failed",
            error=result.error,
        )

        return result

    except Exception as exc:
        error = str(exc)

        # Se o executor ou a persistência do resultado falhar,
        # garantimos que o job não permaneça preso em running.
        try:
            current_job = get_render_job(int(job_id))

            if (
                current_job is not None
                and current_job.get("status") == "running"
            ):
                transition_render_job(
                    int(job_id),
                    "failed",
                    error=error,
                )
        except ValueError:
            # Não mascaramos o erro original.
            pass

        return RenderExecutionResult(
            success=False,
            output_path=None,
            error=error,
        )


def execute_render_job(
    job_id: int,
    executor: AbstractRenderExecutor | None = None,
) -> RenderExecutionResult:
    """
    Executa um Render Job específico.

    Contrato:

        queued
          ↓
        running
          ↓
        executor
          ↓
        completed | failed

    Este fluxo é usado quando o chamador já conhece o ID do job.
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

    # Reserva o job e incrementa attempt exatamente uma vez.
    running_job = transition_render_job(
        job_id,
        "running",
    )

    return _execute_running_render_job(
        running_job,
        executor=executor,
    )


def execute_next_render_job(
    executor: AbstractRenderExecutor | None = None,
) -> RenderExecutionResult | None:
    """
    Executa exatamente um Render Job queued.

    A seleção e reserva são atômicas e pertencem exclusivamente
    a claim_next_render_job().

    Fluxo:

        claim_next_render_job()
              ↓
        queued → running
              ↓
        executor
              ↓
        completed | failed
    """

    running_job = claim_next_render_job()

    if running_job is None:
        return None

    return _execute_running_render_job(
        running_job,
        executor=executor,
    )
