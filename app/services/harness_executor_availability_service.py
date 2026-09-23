from __future__ import annotations

from typing import Any, Iterable

from app.services.capability_execution_contract_service import (
    CAN_MUTATE_CANDIDATE,
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
    required_operations = tuple(sorted(explicit_operations | derived_operations))
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


def _compatible_candidates(
    task: dict[str, Any],
    *,
    blocked_capability_ids: set[str],
) -> list[dict[str, Any]]:
    contract = _effective_task_contract(task)
    required_operations = contract["required_operations"]
    required_side_effect = contract["required_side_effect_class"]
    candidate_requirement = contract["candidate_requirement"]
    action = str(task.get("action") or task.get("authorized_action") or "").strip()
    candidates: list[dict[str, Any]] = []

    for record in sorted(
        GLOBAL_CAPABILITY_REGISTRY.all(),
        key=lambda item: item.capability_id,
    ):
        capability_id = str(record.capability_id)
        if capability_id in blocked_capability_ids:
            continue
        if capability_id in _EXECUTION_TOPOLOGY_CAPABILITY_IDS:
            continue
        if record.capability_type == "PROVIDER" or not record.execution_enabled:
            continue
        if action not in tuple(record.allowed_actions or ()):
            continue
        if not registry_executor_is_task_adapter_compatible(record.executor_binding):
            continue
        if capability_execution_contract_rejection(record, required_operations):
            continue

        mutation_capable = _mutation_capable(record)
        if required_side_effect in {"BOUNDED_MUTATION", "MUTATING"}:
            if not mutation_capable:
                continue
        elif required_side_effect == "READ_ONLY" and mutation_capable:
            continue

        supported_operations = {
            str(item).strip()
            for item in (record.execution_operations or ())
            if str(item).strip()
        }
        if (
            candidate_requirement in {"REQUIRED", "CONDITIONAL"}
            and CAN_MUTATE_CANDIDATE not in supported_operations
        ):
            continue

        security_boundary = str(record.security_boundary or "")
        if "harness" not in security_boundary.casefold():
            continue

        health = capability_health(capability_id)
        if str(health.state).upper() in _BLOCKING_HEALTH_STATES:
            continue

        candidates.append({
            "capability_id": capability_id,
            "health_state": str(health.state),
            "required_operations": list(required_operations),
            "execution_contract_compatible": True,
            "authority_compatible": True,
            "side_effect_class_compatible": True,
            "candidate_artifact_capable": (
                CAN_MUTATE_CANDIDATE in supported_operations
                if candidate_requirement in {"REQUIRED", "CONDITIONAL"}
                else True
            ),
            "provider_id": str(record.provider_id or ""),
            "agent_id": str(record.agent_id or ""),
        })
    return candidates


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
        alternatives = _compatible_candidates(
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
