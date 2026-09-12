from inspect import signature
from app.database.render_queue_repository import (
    claim_next_render_job,
    claim_render_job,
    get_render_job,
    transition_render_job,
    update_render_job_payload,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    NullRenderExecutor,
    RenderExecutionResult,
)
from app.services.video_render_completion_service import (
    complete_video_from_render_job,
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
        execute_kwargs = {}

        if "on_dispatch" in signature(selected_executor.execute).parameters:
            execute_kwargs["on_dispatch"] = (
                lambda github_execution: update_render_job_payload(
                    int(job_id),
                    github_execution=github_execution,
                )
            )

        result = selected_executor.execute(
            running_job,
            **execute_kwargs,
        )

        if not isinstance(result, RenderExecutionResult):
            raise TypeError(
                "O executor deve retornar RenderExecutionResult."
            )

        if result.pending:
            if not result.github_execution or result.success or result.error:
                raise ValueError("Invalid pending cloud execution")
            return result

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

            completed_job = get_render_job(int(job_id))

            if (
                completed_job is not None
                and completed_job.get("video_id") is not None
            ):
                complete_video_from_render_job(int(job_id))

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

    O job precisa estar queued.

    A reserva é feita exclusivamente por claim_render_job(job_id),
    garantindo queued -> running e incremento único do attempt.

    Fluxo:

        queued
          ↓
        claim_render_job(job_id)
          ↓
        running
          ↓
        executor
          ↓
        completed | failed
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

    running_job = claim_render_job(job_id)

    return _execute_running_render_job(
        running_job,
        executor=executor,
    )


def execute_next_render_job(
    executor: AbstractRenderExecutor | None = None,
    execution_context: dict | None = None,
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

    running_job = claim_next_render_job(
        execution_context=execution_context,
    )

    if running_job is None:
        return None

    return _execute_running_render_job(
        running_job,
        executor=executor,
    )


def resume_cloud_render_job(job_id, executor):
    """Resume collection from the existing backend, without another dispatch."""
    job = get_render_job(job_id)
    if not job or job.get("status") != "running" or not job.get("github_execution"):
        raise ValueError("No recoverable running cloud execution")
    return _execute_running_render_job(job, executor)
