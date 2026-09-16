from inspect import signature

from app.database.render_queue_repository import (
    claim_next_render_job,
    claim_render_job,
    get_render_job,
    transition_render_job,
    update_render_job_payload,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    validate_harness_authorization,
)
from app.services.render_executor_service import (
    AbstractRenderExecutor,
    NullRenderExecutor,
    RenderExecutionResult,
)
from app.services.video_render_completion_service import complete_video_from_render_job


def _execute_running_render_job(
    running_job: dict,
    executor: AbstractRenderExecutor | None = None,
) -> RenderExecutionResult:
    """Executa um Render Job que já foi reservado como running."""
    job_id = running_job.get("id")
    if job_id is None:
        raise ValueError("Render Job running não possui id persistido.")
    selected_executor = executor or NullRenderExecutor()
    dispatch_metadata_persisted = False

    def _persist_dispatch_metadata(github_execution):
        nonlocal dispatch_metadata_persisted
        update_render_job_payload(
            int(job_id),
            github_execution=github_execution,
        )
        dispatch_metadata_persisted = True

    try:
        execute_kwargs = {}
        if "on_dispatch" in signature(selected_executor.execute).parameters:
            execute_kwargs["on_dispatch"] = _persist_dispatch_metadata
        result = selected_executor.execute(running_job, **execute_kwargs)
        if not isinstance(result, RenderExecutionResult):
            raise TypeError("O executor deve retornar RenderExecutionResult.")
        if result.pending:
            if not result.github_execution or result.success or result.error:
                raise ValueError("Invalid pending cloud execution")
            return result
        if result.success:
            if not result.output_path:
                raise ValueError(
                    "RenderExecutionResult de sucesso precisa possuir output_path."
                )
            if result.github_execution and not dispatch_metadata_persisted:
                update_render_job_payload(
                    int(job_id),
                    github_execution=result.github_execution,
                )
            transition_render_job(
                int(job_id),
                "completed",
                output_path=result.output_path,
            )
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


def reconcile_running_cloud_render_job_metadata(
    job_id: int,
    executor: AbstractRenderExecutor,
    *,
    execution_context: dict | None,
) -> RenderExecutionResult:
    """Reconcile a persisted cloud run by metadata only.

    This is a control-plane operation. It never downloads the media artifact.
    A fresh Harness EXECUTION authorization is required and consumed once the
    observation/reconciliation step has completed successfully as an operation,
    including a legitimate pending observation.
    """
    if execution_context is None:
        raise PermissionError("Harness execution context is required for cloud reconciliation")
    execution_id = execution_context.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise PermissionError("Harness execution_id is required for cloud reconciliation")
    authorization = validate_harness_authorization(
        execution_context,
        expected_action="EXECUTION",
        expected_subject="action:EXECUTION",
        expected_execution_id=execution_id,
    )
    job = get_render_job(job_id)
    if not job or job.get("status") != "running" or not job.get("github_execution"):
        raise ValueError("No running cloud execution is available for metadata reconciliation")
    reconcile = getattr(executor, "reconcile_metadata_only", None)
    if not callable(reconcile):
        raise TypeError("Executor does not support metadata-only cloud reconciliation")

    result = reconcile(job)
    if not isinstance(result, RenderExecutionResult):
        raise TypeError("Cloud reconciler must return RenderExecutionResult")

    if result.pending:
        if result.success or result.error or not result.github_execution:
            raise ValueError("Invalid pending cloud reconciliation result")
        consume_harness_authorization(authorization)
        return result

    if result.success:
        if not result.output_path:
            raise ValueError("Successful cloud reconciliation requires output_path")
        if not result.github_execution:
            raise ValueError("Successful cloud reconciliation requires github_execution")
        update_render_job_payload(
            job_id,
            github_execution=result.github_execution,
        )
        transition_render_job(
            job_id,
            "completed",
            output_path=result.output_path,
        )
        completed_job = get_render_job(job_id)
        if completed_job is not None and completed_job.get("video_id") is not None:
            complete_video_from_render_job(job_id)
        consume_harness_authorization(authorization)
        return result

    if not result.error:
        raise ValueError("Failed cloud reconciliation requires error")
    transition_render_job(job_id, "failed", error=result.error)
    consume_harness_authorization(authorization)
    return result


def execute_render_job(
    job_id: int,
    executor: AbstractRenderExecutor | None = None,
    execution_context: dict | None = None,
) -> RenderExecutionResult:
    render_job = get_render_job(job_id)
    if render_job is None:
        raise ValueError(f"Render job não encontrado: {job_id}")
    current_status = render_job.get("status")
    if current_status != "queued":
        raise ValueError(
            f"Render job {job_id} não está em estado queued: {current_status}"
        )
    running_job = claim_render_job(job_id, execution_context=execution_context)
    return _execute_running_render_job(running_job, executor=executor)


def execute_next_render_job(
    executor: AbstractRenderExecutor | None = None,
    execution_context: dict | None = None,
) -> RenderExecutionResult | None:
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
    """Collect a proven retry run without dispatching a new workflow."""
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
    if not replacement.get("run_id") or int(replacement["run_id"]) == int(
        expected_previous_run_id
    ):
        raise ValueError("Proven retry must identify a distinct GitHub run")
    for key in ("repository", "workflow"):
        if replacement.get(key) != previous.get(key):
            raise ValueError(f"Proven retry {key} does not match persisted execution")
    rebound = update_render_job_payload(job_id, github_execution=replacement)
    return _execute_running_render_job(rebound, executor=executor)


def rebind_running_cloud_render_job_metadata(
    job_id: int,
    executor: AbstractRenderExecutor,
    *,
    expected_previous_run_id: int,
    proven_github_execution: dict,
    expected_video_id: int,
    expected_execution_id: str,
    execution_context: dict | None,
) -> RenderExecutionResult:
    """Rebind a proven retry run and reconcile it without downloading media.

    The RenderJob identity is preserved. Only the persisted GitHub execution is
    rebound after strict identity checks. Reconciliation then uses the executor's
    metadata-only surface, so this control-plane path never downloads the MP4.
    """
    if execution_context is None:
        raise PermissionError("Harness execution context is required for retry rebind")
    validate_harness_authorization(
        execution_context,
        expected_action="EXECUTION",
        expected_subject="action:EXECUTION",
        expected_execution_id=expected_execution_id,
    )

    job = get_render_job(job_id)
    if not job or job.get("status") != "running" or not job.get("github_execution"):
        raise ValueError("No recoverable running cloud execution")
    if job.get("video_id") != expected_video_id:
        raise ValueError("Render job video_id does not match proven retry")
    if job.get("execution_id") != expected_execution_id:
        raise ValueError("Render job execution_id does not match proven retry")

    previous = job.get("github_execution") or {}
    previous_run_id = previous.get("run_id")
    if not isinstance(previous_run_id, int) or isinstance(previous_run_id, bool):
        raise ValueError("Persisted GitHub execution does not contain valid run_id")
    if previous_run_id != int(expected_previous_run_id):
        raise ValueError("Persisted GitHub execution changed before reconciliation")

    replacement = dict(proven_github_execution or {})
    replacement_run_id = replacement.get("run_id")
    if (
        not isinstance(replacement_run_id, int)
        or isinstance(replacement_run_id, bool)
        or replacement_run_id <= 0
        or replacement_run_id == previous_run_id
    ):
        raise ValueError("Proven retry must identify a distinct positive GitHub run")

    for key in ("repository", "workflow", "ref"):
        if replacement.get(key) != previous.get(key):
            raise ValueError(f"Proven retry {key} does not match persisted execution")
    previous_artifact = previous.get("artifact_name")
    replacement_artifact = replacement.get("artifact_name")
    if previous_artifact is not None and replacement_artifact != previous_artifact:
        raise ValueError("Proven retry artifact_name does not match persisted execution")

    rebound = update_render_job_payload(job_id, github_execution=replacement)
    if not rebound or rebound.get("status") != "running":
        raise RuntimeError("Retry rebind did not preserve running RenderJob state")
    if rebound.get("id") != job_id:
        raise RuntimeError("Retry rebind changed RenderJob identity")

    return reconcile_running_cloud_render_job_metadata(
        job_id,
        executor,
        execution_context=execution_context,
    )


def resume_cloud_render_job(job_id, executor):
    """Resume collection from the existing backend, without another dispatch."""
    job = get_render_job(job_id)
    if not job or job.get("status") != "running" or not job.get("github_execution"):
        raise ValueError("No recoverable running cloud execution")
    return _execute_running_render_job(job, executor)
