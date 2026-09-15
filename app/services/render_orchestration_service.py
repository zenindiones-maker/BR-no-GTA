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
from app.services.video_render_completion_service import complete_video_from_render_job


def _execute_running_render_job(running_job: dict, executor: AbstractRenderExecutor | None = None) -> RenderExecutionResult:
    """Executa um Render Job que já foi reservado como running."""
    job_id = running_job.get("id")
    if job_id is None:
        raise ValueError("Render Job running não possui id persistido.")
    selected_executor = executor or NullRenderExecutor()
    try:
        execute_kwargs = {}
        if "on_dispatch" in signature(selected_executor.execute).parameters:
            execute_kwargs["on_dispatch"] = lambda github_execution: update_render_job_payload(
                int(job_id), github_execution=github_execution
            )
        result = selected_executor.execute(running_job, **execute_kwargs)
        if not isinstance(result, RenderExecutionResult):
            raise TypeError("O executor deve retornar RenderExecutionResult.")
        if result.pending:
            if not result.github_execution or result.success or result.error:
                raise ValueError("Invalid pending cloud execution")
            return result
        if result.success:
            if not result.output_path:
                raise ValueError("RenderExecutionResult de sucesso precisa possuir output_path.")
            transition_render_job(int(job_id), "completed", output_path=result.output_path)
            completed_job = get_render_job(int(job_id))
            if completed_job is not None and completed_job.get("video_id") is not None:
                complete_video_from_render_job(int(job_id))
            return result
        if not result.error:
            raise ValueError("RenderExecutionResult de falha precisa possuir error.")
        transition_render_job(int(job_id), "failed", error=result.error)
        return result
    except Exception as exc:
        error = str(exc)
        try:
            current_job = get_render_job(int(job_id))
            if current_job is not None and current_job.get("status") == "running":
                transition_render_job(int(job_id), "failed", error=error)
        except ValueError:
            pass
        return RenderExecutionResult(success=False, output_path=None, error=error)


def execute_render_job(job_id: int, executor: AbstractRenderExecutor | None = None, execution_context: dict | None = None) -> RenderExecutionResult:
    render_job = get_render_job(job_id)
    if render_job is None:
        raise ValueError(f"Render job não encontrado: {job_id}")
    current_status = render_job.get("status")
    if current_status != "queued":
        raise ValueError(f"Render job {job_id} não está em estado queued: {current_status}")
    running_job = claim_render_job(job_id, execution_context=execution_context)
    return _execute_running_render_job(running_job, executor=executor)


def execute_next_render_job(executor: AbstractRenderExecutor | None = None, execution_context: dict | None = None) -> RenderExecutionResult | None:
    running_job = claim_next_render_job(execution_context=execution_context)
    if running_job is None:
        return None
    return _execute_running_render_job(running_job, executor=executor)


def reconcile_cloud_render_execution(
    job_id: int,
    executor: AbstractRenderExecutor,
    *,
    expected_previous_run_id: int,
    proven_github_execution: dict,
    expected_video_id: int,
    expected_execution_id: str,
) -> RenderExecutionResult:
    """Collect a proven retry run without dispatching a new workflow.

    The caller must establish external provenance. This boundary then protects
    the canonical DB mutation with the persisted Job identity and previous
    run-id as compare-and-set guards before replacing github_execution.
    """
    job = get_render_job(job_id)
    if not job or job.get("status") != "running" or not job.get("github_execution"):
        raise ValueError("No recoverable running cloud execution")
    if job.get("video_id") != expected_video_id:
        raise ValueError("Render job video_id does not match proven retry")
    if job.get("execution_id") != expected_execution_id:
        raise ValueError("Render job execution_id does not match proven retry")
    previous = job.get("github_execution") or {}
    if int(previous.get("run_id", -1)) != int(expected_previous_run_id):
        raise ValueError("Persisted GitHub execution changed before reconciliation")
    replacement = dict(proven_github_execution)
    if not replacement.get("run_id") or int(replacement["run_id"]) == int(expected_previous_run_id):
        raise ValueError("Proven retry must identify a distinct GitHub run")
    for key in ("repository", "workflow"):
        if replacement.get(key) != previous.get(key):
            raise ValueError(f"Proven retry {key} does not match persisted execution")
    rebound = update_render_job_payload(job_id, github_execution=replacement)
    return _execute_running_render_job(rebound, executor=executor)


def resume_cloud_render_job(job_id, executor):
    """Resume collection from the existing backend, without another dispatch."""
    job = get_render_job(job_id)
    if not job or job.get("status") != "running" or not job.get("github_execution"):
        raise ValueError("No recoverable running cloud execution")
    return _execute_running_render_job(job, executor)
