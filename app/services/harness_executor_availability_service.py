from __future__ import annotations

import time
from typing import Any, Iterable

from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_MUTATE_CANDIDATE,
    CAN_PRODUCE_ARTIFACT_REFS,
    CAN_REVIEW,
    CAN_SEMANTIC_REASONING,
    CAN_WRITE_REPOSITORY,
    capability_execution_contract_rejection,
    derive_required_operations,
    effective_candidate_requirement,
    effective_side_effect_class,
)
from app.services.capability_health_service import capability_health
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_executor_contract_service import (
    registry_executor_is_task_adapter_compatible,
)


_EXECUTION_TOPOLOGY_CAPABILITY_IDS = {
    "agent-office.execute",
    "collaboration.hermes.execute",
}
_BLOCKING_HEALTH_STATES = {"BLOCKED", "QUARANTINED"}


def _runtime_eligibility_snapshot() -> dict[str, dict[str, Any]]:
    """Facts proven on this runner; consumed by generic eligibility, never task IDs."""
    import json
    import os
    raw = str(os.getenv("BR_RUNTIME_CAPABILITY_ELIGIBILITY_JSON") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_eligibility(capability_id: str) -> dict[str, Any] | None:
    item = _runtime_eligibility_snapshot().get(str(capability_id))
    return dict(item) if isinstance(item, dict) else None


def _mutation_capable(record: Any) -> bool:
    side_effect_class = str(
        getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
    ).strip().upper()
    return (
        side_effect_class in {"BOUNDED_MUTATION", "MUTATING"}
        or bool(tuple(getattr(record, "default_write_scope", ()) or ()))
    )


def _effective_task_contract(task: dict[str, Any]) -> dict[str, Any]:
    explicit_operations = {
        str(item).strip()
        for item in (task.get("required_operations") or ())
        if str(item).strip()
    }
    derived_operations = set(derive_required_operations(task))
    if explicit_operations:
        # Typed operations from the checkpoint are authoritative. Deterministic
        # safety enrichment may add concrete execution primitives inferred from
        # candidate/benchmark/review semantics, but it must not invent a new
        # semantic-provider dependency merely because prose says "analysis".
        required_operations = tuple(sorted(
            explicit_operations
            | (derived_operations - {CAN_SEMANTIC_REASONING})
        ))
    else:
        required_operations = tuple(sorted(derived_operations))
    candidate_requirement = effective_candidate_requirement(
        str(task.get("candidate_requirement") or "NOT_APPLICABLE"),
        required_operations,
    )
    required_side_effect = effective_side_effect_class(
        str(task.get("risk_side_effect_class") or "READ_ONLY"),
        required_operations,
    )
    return {
        "required_operations": required_operations,
        "candidate_requirement": candidate_requirement,
        "required_side_effect_class": required_side_effect,
    }


def _candidate_artifact_capable(
    record: Any,
    *,
    candidate_requirement: str,
    required_operations: tuple[str, ...],
) -> bool:
    supported_operations = {
        str(item).strip()
        for item in (record.execution_operations or ())
        if str(item).strip()
    }
    if CAN_PRODUCE_ARTIFACT_REFS not in supported_operations:
        return False
    if candidate_requirement not in {"REQUIRED", "CONDITIONAL"}:
        return True
    if (
        CAN_MUTATE_CANDIDATE in required_operations
        or CAN_WRITE_REPOSITORY in required_operations
    ):
        return (
            CAN_MUTATE_CANDIDATE in supported_operations
            and CAN_WRITE_REPOSITORY in supported_operations
        )
    return True


def _evaluate_candidate(
    record: Any,
    *,
    action: str,
    blocked_capability_ids: set[str],
    required_operations: tuple[str, ...],
    required_side_effect: str,
    candidate_requirement: str,
    required_domains: tuple[str, ...] = (),
) -> dict[str, Any]:
    capability_id = str(record.capability_id)
    allowed_actions = tuple(record.allowed_actions or ())
    executor_binding = str(record.executor_binding or "")
    adapter_compatible = registry_executor_is_task_adapter_compatible(
        record.executor_binding
    )
    contract_rejection = capability_execution_contract_rejection(
        record,
        required_operations,
    )
    side_effect_class = str(
        getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
    ).strip().upper()
    mutation_capable = _mutation_capable(record)
    domain = str(getattr(record, "domain", "") or "").strip().casefold()
    normalized_required_domains = tuple(
        str(item).strip().casefold()
        for item in required_domains
        if str(item).strip()
    )
    domain_compatible = (
        not normalized_required_domains
        or any(
            domain == item
            or domain.startswith(item + "/")
            or domain.startswith(item + "-")
            for item in normalized_required_domains
        )
    )
    side_effect_compatible = (
        mutation_capable
        if required_side_effect in {"BOUNDED_MUTATION", "MUTATING"}
        else not mutation_capable
    )
    security_boundary = str(record.security_boundary or "")
    authority_compatible = bool(
        record.execution_enabled
        and record.capability_type != "PROVIDER"
        and capability_id not in _EXECUTION_TOPOLOGY_CAPABILITY_IDS
        and action in allowed_actions
        and adapter_compatible
        and "harness" in security_boundary.casefold()
    )
    candidate_artifact_capable = _candidate_artifact_capable(
        record,
        candidate_requirement=candidate_requirement,
        required_operations=required_operations,
    )

    health_state = "NOT_EVALUATED"
    health_source = "NOT_EVALUATED"
    final_rejection_reason = "ACCEPTED"
    runtime_eligibility = _runtime_eligibility(capability_id)

    if runtime_eligibility and not bool(runtime_eligibility.get("eligible", False)):
        final_rejection_reason = "runtime-hard-ineligible:" + str(runtime_eligibility.get("reason") or "preflight")
    elif capability_id in blocked_capability_ids:
        final_rejection_reason = "blocked-capability-id"
    elif capability_id in _EXECUTION_TOPOLOGY_CAPABILITY_IDS:
        final_rejection_reason = "execution-topology-not-task-capability"
    elif record.capability_type == "PROVIDER":
        final_rejection_reason = "provider-not-task-executor"
    elif not record.execution_enabled:
        final_rejection_reason = "execution-disabled"
    elif action not in allowed_actions:
        final_rejection_reason = "allowed-action-incompatible"
    elif not domain_compatible:
        final_rejection_reason = "domain-incompatible"
    elif not adapter_compatible:
        final_rejection_reason = "executor-adapter-incompatible"
    elif contract_rejection:
        final_rejection_reason = contract_rejection
    elif not side_effect_compatible:
        final_rejection_reason = "side-effect-class-incompatible"
    elif not candidate_artifact_capable:
        final_rejection_reason = "candidate-artifact-capability-insufficient"
    elif "harness" not in security_boundary.casefold():
        final_rejection_reason = "harness-authority-boundary-missing"
    else:
        if runtime_eligibility and bool(runtime_eligibility.get("eligible", False)):
            health_state = str(runtime_eligibility.get("health_state") or "HEALTHY").upper()
            health_source = "RUNTIME_ELIGIBILITY_PREFLIGHT"
        else:
            health = capability_health(capability_id)
            health_state = str(health.state).upper()
            health_source = str(getattr(health, "source", "UNKNOWN") or "UNKNOWN")
        if health_state in _BLOCKING_HEALTH_STATES:
            final_rejection_reason = "health:" + health_state.casefold()

    supported_operations = sorted({
        str(item).strip()
        for item in (record.execution_operations or ())
        if str(item).strip()
    })
    supported_set = set(supported_operations)
    health_policy = str(getattr(record, "health_policy", "") or "")
    if final_rejection_reason == "ACCEPTED":
        rejection_class = "ACCEPTED"
    elif capability_id in _EXECUTION_TOPOLOGY_CAPABILITY_IDS or record.capability_type == "PROVIDER":
        rejection_class = "CAPABILITY_NOT_REVIEWER"
    elif final_rejection_reason == "allowed-action-incompatible":
        rejection_class = "ACTION_MISMATCH"
    elif final_rejection_reason == "domain-incompatible":
        rejection_class = "DOMAIN_MISMATCH"
    elif final_rejection_reason == "side-effect-class-incompatible":
        rejection_class = "SIDE_EFFECT_MISMATCH"
    elif final_rejection_reason.startswith("health:"):
        rejection_class = (
            "AUTH_BLOCKED"
            if health_policy == "CODEX_AUTH_REQUIRED"
            else "HEALTH_BLOCKED"
        )
    elif (
        CAN_REVIEW in required_operations
        and (
            not bool(getattr(record, "supports_review", False))
            or CAN_REVIEW not in supported_set
        )
    ):
        rejection_class = "MISSING_CAN_REVIEW"
    elif (
        CAN_SEMANTIC_REASONING in required_operations
        and CAN_SEMANTIC_REASONING not in supported_set
    ):
        rejection_class = "MISSING_SEMANTIC_REASONING"
    elif (
        (
            CAN_CONSUME_ARTIFACT_REFS in required_operations
            and CAN_CONSUME_ARTIFACT_REFS not in supported_set
        )
        or (
            CAN_PRODUCE_ARTIFACT_REFS in required_operations
            and CAN_PRODUCE_ARTIFACT_REFS not in supported_set
        )
    ):
        rejection_class = "MISSING_ARTIFACT_CONTRACT"
    elif "authorization" in final_rejection_reason or "harness-authority" in final_rejection_reason:
        rejection_class = "AUTH_BLOCKED"
    else:
        rejection_class = "CAPABILITY_NOT_REVIEWER" if CAN_REVIEW in required_operations else "CONTRACT_MISMATCH"

    diagnostic = {
        "CAPABILITY_ID": capability_id,
        "HEALTH": health_state,
        "DOMAIN": str(getattr(record, "domain", "") or ""),
        "EXECUTION_ENABLED": bool(record.execution_enabled),
        "ALLOWED_ACTIONS": list(allowed_actions),
        "EXECUTOR_BINDING": executor_binding,
        "EXECUTOR_ADAPTER_COMPATIBLE": bool(adapter_compatible),
        "EXECUTION_OPERATIONS": supported_operations,
        "REQUIRED_OPERATIONS": list(required_operations),
        "EXECUTION_CONTRACT_REJECTION": contract_rejection,
        "SIDE_EFFECT_CLASS": side_effect_class,
        "REQUIRED_SIDE_EFFECT_CLASS": required_side_effect,
        "SIDE_EFFECT_COMPATIBLE": bool(side_effect_compatible),
        "DOMAIN_COMPATIBLE": bool(domain_compatible),
        "REQUIRED_DOMAINS": list(normalized_required_domains),
        "SUPPORTS_REVIEW": bool(getattr(record, "supports_review", False)),
        "CAN_REVIEW": CAN_REVIEW in supported_set,
        "CAN_SEMANTIC_REASONING": CAN_SEMANTIC_REASONING in supported_set,
        "CAN_CONSUME_ARTIFACT_REFS": CAN_CONSUME_ARTIFACT_REFS in supported_set,
        "CAN_PRODUCE_ARTIFACT_REFS": CAN_PRODUCE_ARTIFACT_REFS in supported_set,
        "DEFAULT_WRITE_SCOPE": list(record.default_write_scope or ()),
        "SECURITY_BOUNDARY": security_boundary,
        "AUTHORITY_COMPATIBLE": bool(authority_compatible),
        "HEALTH_STATE": health_state,
        "HEALTH_SOURCE": health_source,
        "CANDIDATE_REQUIREMENT": candidate_requirement,
        "CANDIDATE_ARTIFACT_CAPABLE": bool(candidate_artifact_capable),
        "RUNTIME_ELIGIBILITY": runtime_eligibility,
        "FINAL_REJECTION_REASON": final_rejection_reason,
        "REJECTION_REASON": rejection_class,
    }
    return diagnostic


def _compatible_candidates(
    task: dict[str, Any],
    *,
    blocked_capability_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contract = _effective_task_contract(task)
    required_operations = contract["required_operations"]
    required_side_effect = contract["required_side_effect_class"]
    candidate_requirement = contract["candidate_requirement"]
    action = str(task.get("action") or task.get("authorized_action") or "").strip()
    required_domains = tuple(
        str(item).strip()
        for item in (
            task.get("required_domains")
            or ([task.get("domain")] if task.get("domain") else [])
        )
        if str(item).strip()
    )
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for record in sorted(
        GLOBAL_CAPABILITY_REGISTRY.all(),
        key=lambda item: item.capability_id,
    ):
        diagnostic = _evaluate_candidate(
            record,
            action=action,
            blocked_capability_ids=blocked_capability_ids,
            required_operations=required_operations,
            required_side_effect=required_side_effect,
            candidate_requirement=candidate_requirement,
            required_domains=required_domains,
        )
        diagnostics.append(diagnostic)
        if diagnostic["FINAL_REJECTION_REASON"] != "ACCEPTED":
            continue

        candidates.append({
            "capability_id": str(record.capability_id),
            "health_state": diagnostic["HEALTH_STATE"],
            "health_source": diagnostic["HEALTH_SOURCE"],
            "required_operations": list(required_operations),
            "execution_contract_compatible": True,
            "authority_compatible": True,
            "side_effect_class_compatible": True,
            "candidate_artifact_capable": True,
            "provider_id": str(record.provider_id or ""),
            "agent_id": str(record.agent_id or ""),
        })
    return candidates, diagnostics


def evaluate_typed_requirement_feasibility(
    task: dict[str, Any],
    *,
    blocked_capability_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Cheap Registry/health feasibility check; never chooses a final team."""
    started = time.perf_counter()
    blocked = {
        str(item).strip()
        for item in blocked_capability_ids
        if str(item).strip()
    }
    contract = _effective_task_contract(task)
    candidates, diagnostics = _compatible_candidates(
        task,
        blocked_capability_ids=blocked,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    health_reads = sum(
        1
        for item in diagnostics
        if item.get("HEALTH_STATE") != "NOT_EVALUATED"
    )
    return {
        "schema": "typed-requirement-feasibility/v1",
        "authority": "DEEPSEEK_HARNESS",
        "task_id": str(task.get("task_id") or ""),
        "task_class": str(task.get("task_class") or ""),
        "action": str(task.get("action") or task.get("authorized_action") or ""),
        "required_operations": list(contract["required_operations"]),
        "required_side_effect_class": contract["required_side_effect_class"],
        "required_domains": list(task.get("required_domains") or ()),
        "feasible": bool(candidates),
        "compatible_candidates": candidates,
        "candidate_matrix": diagnostics,
        "DETERMINISTIC_FEASIBILITY_PRECHECK": "PASS",
        "DETERMINISTIC_FEASIBILITY_PRECHECK_MS": round(elapsed_ms, 3),
        "IMPOSSIBLE_REQUIREMENT_DETECTED_BEFORE_PROVIDER": (
            "NOT_APPLICABLE" if candidates else "PASS"
        ),
        "PROVIDER_CALLS_ON_DETERMINISTIC_IMPOSSIBILITY": 0,
        "PROVIDER_CALL_EXECUTED": "NO",
        "SEMANTIC_REPLAN_PERFORMED": "NO",
        "REGISTRY_READ_COUNT": 1,
        "HEALTH_READ_COUNT": health_reads,
        "CAPABILITY_SERIALIZATION_COUNT": len(diagnostics),
        "DUPLICATE_SERIALIZATION_COUNT": 0,
    }


def resolve_blocked_executor_alternatives(
    mission_plan: dict[str, Any],
    *,
    blocked_capability_ids: Iterable[str],
) -> dict[str, Any]:
    """Resolve executor alternatives deterministically from the canonical Registry.

    This function never invokes semantic planning. It only checks the existing
    MissionPlan task contracts against executable Registry records and their
    health state. It does not mutate or replace the MissionPlan.
    """
    blocked = {
        str(item).strip()
        for item in blocked_capability_ids
        if str(item).strip()
    }
    tasks = list(
        ((mission_plan.get("collaboration_plan") or {}).get("tasks") or ())
    )
    blocked_tasks = [
        dict(task)
        for task in tasks
        if str(task.get("capability_id") or "").strip() in blocked
    ]

    task_resolutions: list[dict[str, Any]] = []
    for task in blocked_tasks:
        contract = _effective_task_contract(task)
        alternatives, candidate_diagnostics = _compatible_candidates(
            task,
            blocked_capability_ids=blocked,
        )
        task_resolutions.append({
            "task_id": str(task.get("task_id") or ""),
            "blocked_capability_id": str(task.get("capability_id") or ""),
            "required_operations": list(contract["required_operations"]),
            "candidate_requirement": contract["candidate_requirement"],
            "required_side_effect_class": contract[
                "required_side_effect_class"
            ],
            "alternatives": alternatives,
            "candidate_diagnostics": candidate_diagnostics,
            "task_level_alternative_available": bool(alternatives),
            "TASK_LEVEL_ALTERNATIVE_AVAILABLE": (
                "YES" if alternatives else "NO"
            ),
        })

    complete_alternative = bool(task_resolutions) and all(
        item["alternatives"]
        for item in task_resolutions
    )
    mission_state = (
        "ALTERNATIVE_EXECUTOR_DISCOVERED"
        if complete_alternative
        else "WAITING_FOR_EXTERNAL_AUTH"
    )
    return {
        "schema": "blocked-executor-alternative-resolution/v1",
        "authority": "DEEPSEEK_HARNESS",
        "mission_id": str(mission_plan.get("mission_id") or ""),
        "plan_id": str(mission_plan.get("plan_id") or ""),
        "blocked_capability_ids": sorted(blocked),
        "blocked_tasks": task_resolutions,
        "ALTERNATIVE_EXECUTOR_RESOLUTION_DETERMINISTIC": "PASS",
        "mission_level_complete_alternative_available": bool(complete_alternative),
        "MISSION_LEVEL_COMPLETE_ALTERNATIVE_AVAILABLE": (
            "YES" if complete_alternative else "NO"
        ),
        "ALTERNATIVE_EXECUTOR_AVAILABLE": (
            "YES" if complete_alternative else "NO"
        ),
        "NO_ALTERNATIVE_EXECUTOR_REPLAN": (
            "NOT_APPLICABLE" if complete_alternative else "NO"
        ),
        "PROVIDER_CALL_EXECUTED": "NO",
        "SEMANTIC_REPLAN_PERFORMED": "NO",
        "CANONICAL_MISSION_PLAN_MUTATED": "NO",
        "MISSION_STATE": mission_state,
    }
