from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable, Sequence

from app.database.harness_authorization_repository import (
    list_recent_harness_authorizations,
)
from app.database import harness_learning_repository as learning_repository
from app.database.telegram_user_input_repository import (
    list_recent_telegram_user_inputs,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_ai_provider_service import HarnessAIProviderEvidence
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
)
from app.services.telegram_reasoning_learning_service import (
    TELEGRAM_REASONING_CAPABILITY_ID,
    TELEGRAM_REASONING_TASK_CLASS,
    capture_telegram_reasoning_outcome,
)
from app.services.opencode_executor_profile_service import (
    BASELINE_OPENCODE_EXECUTOR_VERSION,
    OPENCODE_EXECUTOR_SKILL_ID,
    executable_opencode_executor_profile,
)


CommandRunner = Callable[[Sequence[str]], str]


def _dt(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("timestamp is required")
    if "T" not in text:
        text = text.replace(" ", "T") + "Z"
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_json(command_runner: CommandRunner, command: list[str]) -> Any:
    raw = command_runner(command)
    return json.loads(raw)


def _observe_failed_run(
    *,
    repository: str,
    run_id: int,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    run = _safe_json(
        command_runner,
        [
            "gh", "api",
            f"repos/{repository}/actions/runs/{run_id}",
        ],
    )
    jobs_payload = _safe_json(
        command_runner,
        [
            "gh", "api",
            f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
        ],
    )
    jobs = [
        item for item in (jobs_payload.get("jobs") or [])
        if isinstance(item, dict)
    ]
    matches = [
        item for item in jobs
        if any(
            isinstance(step, dict)
            and step.get("name") == "Execute explicit free provider/model"
            for step in (item.get("steps") or [])
        )
    ]
    if len(matches) != 1:
        raise RuntimeError("failed OmniRoute run has no unique execution job")
    job = matches[0]

    try:
        log_text = command_runner([
            "gh", "run", "view", str(run_id),
            "--repo", repository,
            "--log-failed",
        ])
    except Exception:
        log_text = ""
    provider_match = re.findall(r"PROVIDER:\s*([^\s]+)", log_text)
    model_match = re.findall(r"MODEL:\s*([^\s]+)", log_text)
    http_match = re.findall(
        r"HTTP(?: Error)?\s+(\d{3})(?::\s*([^\r\n]+))?",
        log_text,
        flags=re.IGNORECASE,
    )
    exit_match = re.findall(
        r"exit code\s+(\d+)",
        log_text,
        flags=re.IGNORECASE,
    )
    provider = provider_match[-1] if provider_match else None
    model = model_match[-1] if model_match else None
    http_status = int(http_match[-1][0]) if http_match else None
    http_reason = (
        str(http_match[-1][1]).strip()[:200]
        if http_match and http_match[-1][1]
        else None
    )
    exit_code = int(exit_match[-1]) if exit_match else None
    started_at = str(job.get("started_at") or run.get("run_started_at") or "")
    finished_at = str(job.get("completed_at") or run.get("updated_at") or "")
    latency = max(0.0, (_dt(finished_at) - _dt(started_at)).total_seconds())
    return {
        "run_id": int(run["id"]),
        "job_id": int(job["id"]),
        "run_status": str(run.get("status") or ""),
        "run_conclusion": str(run.get("conclusion") or ""),
        "job_status": str(job.get("status") or ""),
        "job_conclusion": str(job.get("conclusion") or ""),
        "head_sha": str(run.get("head_sha") or ""),
        "workflow_path": str(run.get("path") or ""),
        "created_at": str(run.get("created_at") or ""),
        "updated_at": str(run.get("updated_at") or ""),
        "started_at": started_at,
        "finished_at": finished_at,
        "latency_seconds": latency,
        "provider": provider,
        "model": model,
        "http_status": http_status,
        "http_reason": http_reason,
        "exit_code": exit_code,
        "log_sha256": sha256(log_text.encode("utf-8")).hexdigest(),
    }


def _recent_failed_runs(
    *,
    repository: str,
    ref: str,
    command_runner: CommandRunner,
    limit: int,
) -> list[dict[str, Any]]:
    raw = command_runner([
        "gh", "run", "list",
        "--repo", repository,
        "--workflow", "omniroute.yml",
        "--branch", ref,
        "--event", "workflow_dispatch",
        "--limit", str(limit),
        "--json", "databaseId,status,conclusion,headSha,createdAt,updatedAt",
    ])
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise RuntimeError("gh run list returned invalid OmniRoute payload")
    return [
        item for item in payload
        if isinstance(item, dict)
        and str(item.get("status") or "") == "completed"
        and str(item.get("conclusion") or "") != "success"
    ]


def _telegram_reasoning_authorizations() -> list[dict[str, Any]]:
    rows = list_recent_harness_authorizations(limit=200)
    result: list[dict[str, Any]] = []
    for item in rows:
        lineage = item.get("lineage") or {}
        if not isinstance(lineage, dict):
            continue
        if lineage.get("ingress") != "telegram":
            continue
        if lineage.get("capability_id") != TELEGRAM_REASONING_CAPABILITY_ID:
            continue
        if not str(item.get("subject") or "").startswith("provider:"):
            continue
        result.append(item)
    return result


def _match_authorization(
    *,
    observation: dict[str, Any],
    authorizations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    created = _dt(observation["created_at"])
    provider = observation.get("provider")
    model = observation.get("model")
    candidates = []
    for auth in authorizations:
        lineage = auth.get("lineage") or {}
        if provider and lineage.get("selected_provider") != provider:
            continue
        if model and lineage.get("selected_model") != model:
            continue
        issued = _dt(auth["issued_at"])
        delta = (created - issued).total_seconds()
        if -30 <= delta <= 600:
            candidates.append((abs(delta), auth))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        return None
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


def _match_input(
    *,
    authorization: dict[str, Any],
    inputs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lineage = authorization.get("lineage") or {}
    explicit_input_id = lineage.get("telegram_input_id")
    if isinstance(explicit_input_id, int):
        exact = [item for item in inputs if item.get("id") == explicit_input_id]
        return exact[0] if len(exact) == 1 else None

    issued = _dt(authorization["issued_at"])
    candidates = []
    for item in inputs:
        if str(item.get("execution_outcome_status") or "NOT_OBSERVED") != "NOT_OBSERVED":
            continue
        if item.get("classification") not in {"chat", "question", "news", "knowledge_note"}:
            continue
        created = _dt(item.get("created_at"))
        delta = (issued - created).total_seconds()
        if -30 <= delta <= 600:
            candidates.append((abs(delta), item))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        return None
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


def _routing_from_authorization(
    authorization: dict[str, Any],
    observation: dict[str, Any],
) -> HarnessRoutingDecision:
    lineage = authorization.get("lineage") or {}
    routing_id = str(lineage.get("routing_id") or "").strip()
    provider = str(lineage.get("selected_provider") or "").strip()
    model = str(lineage.get("selected_model") or "").strip()
    provider_executor = str(lineage.get("selected_executor_binding") or "").strip()
    if not all((routing_id, provider, model, provider_executor)):
        raise ValueError("persisted Telegram authorization lacks routing provenance")
    if observation.get("provider") and observation["provider"] != provider:
        raise PermissionError("observed provider does not match persisted routing")
    if observation.get("model") and observation["model"] != model:
        raise PermissionError("observed model does not match persisted routing")

    capability = GLOBAL_CAPABILITY_REGISTRY.get(TELEGRAM_REASONING_CAPABILITY_ID)
    if capability is None or not capability.executor_binding:
        raise RuntimeError("ai.reasoning.text Registry binding is unavailable")
    return HarnessRoutingDecision(
        routing_id=routing_id,
        intent="reconciled real Telegram reasoning incident",
        authorized_action=str(authorization["authorized_action"]),
        candidate_capability_ids=(TELEGRAM_REASONING_CAPABILITY_ID,),
        selected_capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
        selected_provider=provider,
        selected_model=model,
        selected_executor_binding=capability.executor_binding,
        selected_provider_executor_binding=provider_executor,
        primary_provider=provider,
        fallback_allowed=False,
        fallback_candidates=(),
        fallback_occurred=False,
        evidence_expectations=(str(capability.evidence_contract or "HarnessAIProviderEvidence"),),
        rationale=(
            "reconciled from persisted Harness authorization",
            "provider/model identity corroborated by GitHub Actions failed-run evidence",
        ),
        rejected_candidates=(),
        policy_metadata={
            "domain": "ai",
            "task_class": TELEGRAM_REASONING_TASK_CLASS,
            "zero_cost_operation": True,
            "historical_reconciliation": True,
            "learning_context": {
                "learning_required": True,
                "learning_participated": False,
                "retrieved_memory_ids": [],
                "retrieved_failure_memory_ids": [],
                "retrieved_human_feedback_ids": [],
                "competence_records": [],
                "active_skill_versions": [],
                "active_policy_versions": [],
            },
        },
    )


def _evidence_from_observation(
    *,
    authorization: dict[str, Any],
    routing: HarnessRoutingDecision,
    observation: dict[str, Any],
) -> HarnessAIProviderEvidence:
    status = observation.get("http_status")
    failure_code = (
        f"upstream_http_{status}"
        if status is not None
        else "omniroute_workflow_failure"
    )
    message = (
        f"OmniRoute/OpenCode upstream returned HTTP {status}"
        if status is not None
        else "OmniRoute GitHub Actions workflow failed"
    )
    if observation.get("http_reason"):
        message += f" {observation['http_reason']}"
    error = {
        "provider": routing.selected_provider,
        "model": routing.selected_model,
        "code": failure_code,
        "status_code": status,
        "retryable": False,
        "message": message[:500],
        "error_type": "ObservedOmniRouteWorkflowFailure",
        "execution_ref": f"github-actions:{observation['run_id']}",
        "run_id": observation["run_id"],
        "job_id": observation["job_id"],
        "workflow_status": observation["run_status"],
        "workflow_conclusion": observation["run_conclusion"],
        "exit_code": observation.get("exit_code"),
        "log_sha256": observation["log_sha256"],
        "commit_sha": observation["head_sha"],
        "retry_count": 0,
    }
    baseline_profile = executable_opencode_executor_profile(
        BASELINE_OPENCODE_EXECUTOR_VERSION
    )
    return HarnessAIProviderEvidence(
        provider=str(routing.selected_provider),
        status="FAILED",
        active=False,
        authority=str(authorization["issued_by"]),
        authorized_action=str(authorization["authorized_action"]),
        harness_decision_id=str(authorization["harness_decision_id"]),
        execution_id=str(authorization["execution_id"]),
        authorization_id=str(authorization["authorization_id"]),
        error=error,
        routing=routing.to_dict(),
        model=str(routing.selected_model),
        executor_binding=str(routing.selected_provider_executor_binding),
        started_at=observation["started_at"],
        finished_at=observation["finished_at"],
        latency_seconds=float(observation["latency_seconds"]),
        retry_count=0,
        evidence_refs=(
            f"github:run:{observation['run_id']}",
            f"github:job:{observation['job_id']}",
            f"github:commit:{observation['head_sha']}",
            f"github:failed-log-sha256:{observation['log_sha256']}",
            f"authorization:{authorization['authorization_id']}",
            f"routing:{routing.routing_id}",
        ),
        provider_profile_skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        provider_profile_version=BASELINE_OPENCODE_EXECUTOR_VERSION,
        provider_profile_content_ref=baseline_profile["content_ref"],
        provider_profile_checksum=baseline_profile["checksum"],
    )


def _existing_reconciled_episode(*, run_id: int, job_id: int) -> dict[str, Any] | None:
    run_ref = f"github:run:{run_id}"
    job_ref = f"github:job:{job_id}"
    for episode in learning_repository.list_episodes(
        domain="ai",
        task_class=TELEGRAM_REASONING_TASK_CLASS,
        capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
        limit=200,
    ):
        refs = set(episode.get("evidence_refs") or ())
        if run_ref in refs and job_ref in refs:
            return episode
    return None


def reconcile_specific_telegram_provider_failure(
    *,
    repository: str,
    run_id: int,
    command_runner: CommandRunner,
    expected_job_id: int | None = None,
    expected_provider: str | None = None,
    expected_model: str | None = None,
    expected_http_status: int | None = None,
    expected_exit_code: int | None = None,
) -> dict[str, Any]:
    """Reconcile one real Telegram provider incident, failing closed on mismatched evidence."""
    observation = _observe_failed_run(
        repository=repository,
        run_id=run_id,
        command_runner=command_runner,
    )
    expectations = {
        "job_id": expected_job_id,
        "provider": expected_provider,
        "model": expected_model,
        "http_status": expected_http_status,
        "exit_code": expected_exit_code,
    }
    mismatches = {
        key: {"expected": expected, "observed": observation.get(key)}
        for key, expected in expectations.items()
        if expected is not None and observation.get(key) != expected
    }
    if mismatches:
        raise PermissionError(
            "Telegram incident evidence mismatch: "
            + json.dumps(mismatches, sort_keys=True)
        )
    if observation.get("run_status") != "completed":
        raise RuntimeError("Telegram provider incident run is not terminal")
    if observation.get("run_conclusion") == "success":
        raise RuntimeError("Telegram provider incident is not a failed run")

    existing = _existing_reconciled_episode(
        run_id=run_id,
        job_id=int(observation["job_id"]),
    )
    if existing is not None:
        lineage = dict(existing.get("lineage") or {})
        # The episode is the idempotency authority; memory is resolved by source episode below.
        matching_memories = [
            item for item in learning_repository.list_memories(
                status="ACTIVE",
                memory_type="FAILURE",
                domain="ai",
                task_class=TELEGRAM_REASONING_TASK_CLASS,
                capability_id=TELEGRAM_REASONING_CAPABILITY_ID,
                limit=100,
            )
            if existing["episode_id"] in (item.get("source_episode_ids") or ())
        ]
        return {
            "run_id": run_id,
            "job_id": observation["job_id"],
            "authorization_id": lineage.get("authorization_id"),
            "execution_id": existing.get("execution_id"),
            "routing_id": lineage.get("routing_id"),
            "telegram_input_id": lineage.get("telegram_input_id"),
            "episode_id": existing["episode_id"],
            "failure_memory_id": (
                matching_memories[0]["memory_id"] if matching_memories else None
            ),
            "provider_error": (existing.get("actual_outcome") or {}).get("provider_error"),
            "INPUT_MEMORY_CAPTURED": (existing.get("qa_results") or {}).get("INPUT_MEMORY_CAPTURED"),
            "EXECUTION_OUTCOME_LEARNED": "PASS",
            "USER_GOAL_COMPLETED": "NO",
            "IDEMPOTENT": True,
        }

    authorizations = _telegram_reasoning_authorizations()
    authorization = _match_authorization(
        observation=observation,
        authorizations=authorizations,
    )
    if authorization is None:
        raise RuntimeError(
            "No unique persisted Telegram HarnessAuthorization matches the observed provider run"
        )
    inputs = list_recent_telegram_user_inputs(limit=200)
    input_record = _match_input(
        authorization=authorization,
        inputs=inputs,
    )
    if input_record is None:
        raise RuntimeError(
            "No unique persisted Telegram input matches the observed provider authorization"
        )
    routing = _routing_from_authorization(authorization, observation)
    evidence = _evidence_from_observation(
        authorization=authorization,
        routing=routing,
        observation=observation,
    )
    captured = capture_telegram_reasoning_outcome(
        evidence=evidence,
        routing_decision=routing,
        input_record=input_record,
    )
    return {
        "run_id": run_id,
        "job_id": observation["job_id"],
        "authorization_id": authorization["authorization_id"],
        "execution_id": authorization["execution_id"],
        "routing_id": routing.routing_id,
        "telegram_input_id": input_record["id"],
        "episode_id": captured["episode"]["episode_id"],
        "failure_memory_id": captured["failure_memory"]["memory_id"],
        "provider_error": evidence.error,
        "INPUT_MEMORY_CAPTURED": captured["INPUT_MEMORY_CAPTURED"],
        "EXECUTION_OUTCOME_LEARNED": captured["EXECUTION_OUTCOME_LEARNED"],
        "USER_GOAL_COMPLETED": captured["USER_GOAL_COMPLETED"],
        "IDEMPOTENT": False,
    }


def reconcile_recent_unlearned_telegram_provider_failures(
    *,
    repository: str,
    ref: str,
    command_runner: CommandRunner,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Backfill real incidents only when persisted Telegram + Harness + GitHub identities agree."""
    inputs = list_recent_telegram_user_inputs(limit=100)
    authorizations = _telegram_reasoning_authorizations()
    results: list[dict[str, Any]] = []
    for run_summary in _recent_failed_runs(
        repository=repository,
        ref=ref,
        command_runner=command_runner,
        limit=limit,
    ):
        run_id = int(run_summary["databaseId"])
        observation = _observe_failed_run(
            repository=repository,
            run_id=run_id,
            command_runner=command_runner,
        )
        authorization = _match_authorization(
            observation=observation,
            authorizations=authorizations,
        )
        if authorization is None:
            continue
        input_record = _match_input(
            authorization=authorization,
            inputs=inputs,
        )
        if input_record is None:
            continue
        routing = _routing_from_authorization(authorization, observation)
        evidence = _evidence_from_observation(
            authorization=authorization,
            routing=routing,
            observation=observation,
        )
        captured = capture_telegram_reasoning_outcome(
            evidence=evidence,
            routing_decision=routing,
            input_record=input_record,
        )
        results.append({
            "run_id": run_id,
            "job_id": observation["job_id"],
            "authorization_id": authorization["authorization_id"],
            "execution_id": authorization["execution_id"],
            "routing_id": routing.routing_id,
            "telegram_input_id": input_record["id"],
            "episode_id": captured["episode"]["episode_id"],
            "failure_memory_id": captured["failure_memory"]["memory_id"],
            "provider_error": evidence.error,
            "INPUT_MEMORY_CAPTURED": captured["INPUT_MEMORY_CAPTURED"],
            "EXECUTION_OUTCOME_LEARNED": captured["EXECUTION_OUTCOME_LEARNED"],
            "USER_GOAL_COMPLETED": captured["USER_GOAL_COMPLETED"],
        })
    return results
