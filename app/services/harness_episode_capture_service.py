from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from app.services.harness_execution_result import CanonicalExecutionResult
from app.services.harness_learning_service import HarnessEpisode, persist_episode
from app.services.harness_routing_policy_service import HarnessRoutingDecision


def _iso(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    return text


def _seconds(started_at: str, finished_at: str) -> float:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    seconds = (finish - start).total_seconds()
    if seconds < 0:
        raise ValueError("execution finished before it started")
    return seconds


def _stable_episode_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    return "episode-" + sha256(raw.encode("utf-8")).hexdigest()[:24]


def _receipt_from_canonical(canonical: CanonicalExecutionResult) -> dict[str, Any]:
    result = canonical.result
    if not isinstance(result, Mapping):
        raise ValueError("canonical execution result lacks structured result evidence")
    receipt = result.get("receipt")
    if not isinstance(receipt, Mapping):
        raise ValueError("canonical execution result lacks observed execution receipt")
    return dict(receipt)


def capture_canonical_execution_episode(
    canonical: CanonicalExecutionResult,
    *,
    routing_decision: HarnessRoutingDecision,
    domain: str,
    task_class: str,
    skill_version: str | None = None,
    source_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Persist one Episode from a canonical executor receipt, never from agent prose.

    This boundary deliberately requires timestamps, exit status, output/evidence
    references, Harness lineage and return-to-Harness proof. It therefore cannot
    be satisfied by an agent merely claiming that an operation succeeded.
    """
    receipt = _receipt_from_canonical(canonical)
    required = (
        "mission_id", "task_id", "goal_id", "decision_id", "authorization_id",
        "agent_id", "capability", "executor", "started_at",
        "finished_at", "status", "exit_code", "returned_to_harness",
    )
    missing = [key for key in required if receipt.get(key) in (None, "")]
    if missing:
        raise ValueError(f"observed execution receipt missing fields: {missing}")

    selected = routing_decision.policy_metadata.get("selected_implementation")
    selected_skill_id = (
        selected.get("skill_id")
        if isinstance(selected, Mapping)
        else None
    )
    if selected_skill_id:
        if str(receipt.get("skill_id") or "") != str(selected_skill_id):
            raise PermissionError("receipt/routing skill identity mismatch")
    elif receipt.get("skill_id") not in (None, ""):
        raise PermissionError("receipt declares skill_id for a non-skill implementation")

    if str(receipt["decision_id"]) != str(canonical.harness_decision_id):
        raise PermissionError("receipt/canonical Harness decision mismatch")
    if str(receipt["authorization_id"]) != str(canonical.authorization_id):
        raise PermissionError("receipt/canonical authorization mismatch")
    if str(receipt["capability"]) != str(canonical.capability_id):
        raise PermissionError("receipt/canonical capability mismatch")
    if str(receipt["executor"]) != str(canonical.executor):
        raise PermissionError("receipt/canonical executor mismatch")
    if receipt.get("returned_to_harness") is not True:
        raise ValueError("executor receipt was not returned to the Harness")

    started_at = _iso(receipt["started_at"], "receipt.started_at")
    finished_at = _iso(receipt["finished_at"], "receipt.finished_at")
    duration_seconds = _seconds(started_at, finished_at)
    receipt_status = str(receipt["status"]).upper()
    exit_code = receipt["exit_code"]
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise ValueError("receipt.exit_code must be an integer")

    success = bool(canonical.success and receipt_status == "COMPLETED" and exit_code == 0)
    status = "COMPLETED" if success else (
        "BLOCKED" if receipt_status == "BLOCKED" else
        "CANCELLED" if receipt_status == "CANCELLED" else
        "FAILED"
    )
    output_refs = tuple(str(x) for x in (receipt.get("output_refs") or ()) if str(x))
    evidence_refs = tuple(str(x) for x in (receipt.get("evidence_refs") or ()) if str(x))
    if success and not output_refs:
        raise ValueError("successful observed execution requires output refs")
    if not evidence_refs:
        raise ValueError("observed execution requires evidence refs")

    routing = routing_decision.to_dict()
    learning_context = dict(routing_decision.policy_metadata.get("learning_context") or {})
    evidence = tuple(dict.fromkeys([
        *evidence_refs,
        *(f"output:{ref}" for ref in output_refs),
        f"authorization:{canonical.authorization_id}",
        f"routing:{canonical.routing_id}",
    ]))
    identity = {
        "execution_id": canonical.execution_id,
        "task_id": receipt["task_id"],
        "capability_id": canonical.capability_id,
        "agent_id": receipt["agent_id"],
    }
    episode = HarnessEpisode(
        episode_id=_stable_episode_id(identity),
        goal_id=str(receipt["goal_id"]),
        decision_id=str(receipt["decision_id"]),
        execution_id=str(canonical.execution_id or ""),
        task_id=str(receipt["task_id"]),
        agent_id=str(receipt["agent_id"]),
        capability_id=str(canonical.capability_id or ""),
        domain=domain,
        task_class=task_class,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        status=status,
        actual_outcome={
            "observed": True,
            "success": success,
            "canonical_status": canonical.status,
            "receipt_status": receipt_status,
            "exit_code": exit_code,
            "returned_to_harness": True,
        },
        outcome_evidence=evidence,
        skill_id=str(receipt.get("skill_id") or "") or None,
        skill_version=skill_version,
        provider=str(receipt.get("provider") or canonical.provider or "") or None,
        input_refs=tuple(str(x) for x in (receipt.get("input_refs") or ()) if str(x)),
        output_refs=output_refs,
        evidence_refs=evidence,
        tool_calls=({
            "tool": canonical.tool,
            "operation": canonical.operation,
            "executor": canonical.executor,
            "exit_code": exit_code,
            "status": receipt_status,
        },),
        routing_decision=routing,
        error=str(receipt.get("error") or "") or None,
        retry_count=0,
        human_intervention=False,
        qa_results={"status": "PASS" if success else "FAIL"},
        latency_seconds=duration_seconds,
        commit_ref=None,
        run_ref=None,
        artifact_refs=tuple(str(x) for x in canonical.artifacts if str(x)),
        source_versions=dict(source_versions or {}),
        lineage={
            "mission_id": str(receipt["mission_id"]),
            "authorization_id": str(canonical.authorization_id),
            "routing_id": str(canonical.routing_id),
            "harness_decision_id": str(canonical.harness_decision_id),
            "selected_capability_id": routing_decision.selected_capability_id,
            "selected_executor_binding": routing_decision.selected_executor_binding,
            "retrieved_memory_ids": list(learning_context.get("retrieved_memory_ids") or ()),
            "retrieved_failure_memory_ids": list(
                learning_context.get("retrieved_failure_memory_ids") or ()
            ),
            "retrieved_human_feedback_ids": list(
                learning_context.get("retrieved_human_feedback_ids") or ()
            ),
            "competence_records": list(learning_context.get("competence_records") or ()),
            "active_skill_versions": list(learning_context.get("active_skill_versions") or ()),
            "active_policy_versions": list(learning_context.get("active_policy_versions") or ()),
        },
    )
    return persist_episode(episode)
