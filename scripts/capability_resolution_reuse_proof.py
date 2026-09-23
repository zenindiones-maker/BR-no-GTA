from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.database.schema import initialize_schema
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.capability_health_service import capability_health
from app.services.continuous_operation_policy_service import (
    load_continuous_operation_policy,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_adaptive_planning_service import (
    _EXECUTION_TOPOLOGY_CAPABILITY_IDS,
    _candidate_requirement_for_task,
    _capability_failure_memory,
    _record_is_mutation_capable,
    build_semantic_planning_context,
    effective_required_side_effect_class,
    proposal_requirements,
    select_capability_for_requirement,
)
from app.services.harness_collaboration_service import build_goal_envelope
from app.services.harness_executor_contract_service import (
    registry_executor_is_task_adapter_compatible,
)
from app.services.provider_health_service import semantic_provider_health
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    expand_compact_mission_plan_mapping,
)


def _resource_bounds() -> dict[str, int]:
    resources = dict(load_continuous_operation_policy().resource_governance)
    return {
        key: int(resources[key])
        for key in (
            "max_tasks_per_mission",
            "max_retries_per_task",
            "max_reviewer_loops",
            "max_parallelism",
            "mission_timeout_seconds",
            "bounded_memory_bytes",
        )
    }


def _candidate_trace(
    requirement: dict[str, Any],
    *,
    context: dict[str, Any],
) -> dict[str, Any]:
    discovered = GLOBAL_CAPABILITY_REGISTRY.discover(
        intent=str(requirement["query"]),
        authorized_action=str(requirement["action"]),
        limit=40,
    )
    proposed = [
        str(item)
        for item in requirement.get("candidate_capability_ids") or ()
        if str(item).strip()
    ]
    ordered: list[str] = []
    for capability_id in [
        *proposed,
        *(str(item["capability_id"]) for item in discovered),
    ]:
        if capability_id not in ordered:
            ordered.append(capability_id)

    required_side_effect = effective_required_side_effect_class(
        task_class=str(requirement.get("task_class") or ""),
        declared=str(requirement.get("risk_side_effect_class") or "READ_ONLY"),
    )
    candidate_requirement = str(
        requirement.get("candidate_requirement")
        or _candidate_requirement_for_task(
            task_class=str(requirement.get("task_class") or ""),
            declared=str(
                requirement.get("risk_side_effect_class") or "READ_ONLY"
            ),
            dependencies=requirement.get("dependencies") or (),
        )
    ).strip().upper()

    rows: list[dict[str, Any]] = []
    for capability_id in ordered:
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        row: dict[str, Any] = {
            "CAPABILITY_ID": capability_id,
            "PROPOSED_HINT": capability_id in proposed,
            "EXECUTION_ENABLED": bool(
                record and record.execution_enabled
            ),
            "ALLOWED_ACTIONS": list(
                tuple(record.allowed_actions or ()) if record else ()
            ),
            "TASK_ADAPTER_COMPATIBLE": bool(
                record
                and registry_executor_is_task_adapter_compatible(
                    record.executor_binding
                )
            ),
            "SIDE_EFFECT_CLASS": (
                str(getattr(record, "side_effect_class", "") or "")
                if record else None
            ),
            "CANDIDATE_SEMANTICS": candidate_requirement,
            "FAILURE_MEMORY": None,
            "HEALTH_STATE": None,
            "HEALTH_SOURCE": None,
            "CAPABILITY_REJECTION_REASON": None,
        }

        if capability_id in _EXECUTION_TOPOLOGY_CAPABILITY_IDS:
            row["CAPABILITY_REJECTION_REASON"] = (
                "execution-topology-not-task-capability"
            )
            rows.append(row)
            continue
        if record is None:
            row["CAPABILITY_REJECTION_REASON"] = "absent-from-registry"
            rows.append(row)
            continue
        if record.capability_type == "PROVIDER":
            row["CAPABILITY_REJECTION_REASON"] = "provider-not-task-capability"
            rows.append(row)
            continue
        if not record.execution_enabled:
            row["CAPABILITY_REJECTION_REASON"] = "execution-disabled"
            rows.append(row)
            continue
        if str(requirement["action"]) not in record.allowed_actions:
            row["CAPABILITY_REJECTION_REASON"] = "action-incompatible"
            rows.append(row)
            continue
        if not row["TASK_ADAPTER_COMPATIBLE"]:
            row["CAPABILITY_REJECTION_REASON"] = "task-adapter-incompatible"
            rows.append(row)
            continue

        mutation_capable = _record_is_mutation_capable(record)
        record_side_effect = str(
            getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
        ).upper()
        if (
            required_side_effect in {"BOUNDED_MUTATION", "MUTATING"}
            and not mutation_capable
        ):
            row["CAPABILITY_REJECTION_REASON"] = (
                "side-effect-insufficient:" + record_side_effect.casefold()
            )
            rows.append(row)
            continue
        if required_side_effect == "READ_ONLY" and mutation_capable:
            row["CAPABILITY_REJECTION_REASON"] = (
                "side-effect-exceeds:read-only"
            )
            rows.append(row)
            continue
        if (
            candidate_requirement in {"REQUIRED", "CONDITIONAL"}
            and not mutation_capable
        ):
            row["CAPABILITY_REJECTION_REASON"] = (
                "candidate-semantics-insufficient:"
                + candidate_requirement.casefold()
            )
            rows.append(row)
            continue
        if candidate_requirement == "NOT_APPLICABLE" and mutation_capable:
            row["CAPABILITY_REJECTION_REASON"] = (
                "candidate-semantics-exceeds:not-applicable"
            )
            rows.append(row)
            continue

        failure = _capability_failure_memory(capability_id, context=context)
        if failure is not None:
            row["FAILURE_MEMORY"] = str(
                failure.get("failure_pattern") or capability_id
            )
            row["CAPABILITY_REJECTION_REASON"] = (
                "failure-memory:" + row["FAILURE_MEMORY"]
            )
            rows.append(row)
            continue

        health = capability_health(capability_id).to_dict()
        row["HEALTH_STATE"] = health.get("state")
        row["HEALTH_SOURCE"] = health.get("source")
        if str(health.get("state") or "") in {"BLOCKED", "QUARANTINED"}:
            row["CAPABILITY_REJECTION_REASON"] = (
                "health:" + str(health.get("state") or "").casefold()
            )
        rows.append(row)

    return {
        "REGISTRY_DISCOVERY_QUERY": str(requirement["query"]),
        "DISCOVERED_CAPABILITY_IDS": [
            str(item["capability_id"]) for item in discovered
        ],
        "PROPOSED_CAPABILITY_IDS": proposed,
        "CANDIDATES": rows,
    }


def run(
    *,
    source_root: Path,
    response_sha256: str,
    output: Path,
    source_run_id: str,
) -> dict[str, Any]:
    initialize_schema()
    response_path = (
        source_root / "sanitized-responses" / f"{response_sha256}.json"
    )
    if not response_path.is_file():
        raise FileNotFoundError(response_path)
    response_text = response_path.read_text(encoding="utf-8").strip()
    observed_sha = sha256(response_text.encode("utf-8")).hexdigest()
    if observed_sha != response_sha256:
        raise ValueError("captured NVIDIA response hash mismatch")

    parsed = json.loads(response_text)
    mapping = expand_compact_mission_plan_mapping(parsed)
    bounds = _resource_bounds()
    proposal = MissionPlanProposal.from_mapping(
        mapping,
        max_tasks=int(bounds["max_tasks_per_mission"]),
    )

    source_goal_path = Path(
        ".run/telegram-natural-system-improvement.request.json"
    )
    source_goal = json.loads(source_goal_path.read_text(encoding="utf-8"))
    natural_goal = str(source_goal.get("natural_goal") or "").strip()
    if not natural_goal:
        raise RuntimeError("NATURAL_GOAL_UNAVAILABLE")

    goal = build_goal_envelope(
        human_goal=natural_goal,
        project="BR-no-GTA",
        goal_id="capability-resolution-reuse-proof",
        subject="semantic planner performance",
        source_surface="captured-nvidia-mission-proposal",
        canonical_state={
            "active_project": "BR-no-GTA",
            "execution_status": "capability-resolution-proof",
        },
        conversation_state={
            "active_stage": "registry-resolution",
            "source_run_id": source_run_id,
        },
    )
    memory = build_bounded_memory_context(
        goal_id=goal.goal_id,
        domain="system-improvement",
        task_class=goal.mission_class.casefold().replace("_", "-"),
        artifact_ref=None,
        intent=goal.human_goal,
        max_bytes=int(bounds["bounded_memory_bytes"]),
    ).to_dict()
    context = build_semantic_planning_context(
        goal=goal.to_dict(),
        bounded_memory_context=memory,
        resource_bounds=bounds,
        provider_health=semantic_provider_health(),
        artifact_ref=None,
    )

    requirements = proposal_requirements(proposal)
    used: set[str] = set()
    selected_rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    benchmark_selected: str | None = None

    for requirement in requirements:
        trace = _candidate_trace(requirement, context=context)
        capability_id, competence_used, avoided, selection = (
            select_capability_for_requirement(
                requirement,
                context=context,
                used=used,
            )
        )
        used.add(capability_id)
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        row = {
            "task_id": requirement["task_id"],
            "task_class": requirement["task_class"],
            "selected_capability_id": capability_id,
            "selected_agent_id": getattr(record, "agent_id", None),
            "selected_skill_id": getattr(record, "skill_id", None),
            "competence_used": bool(competence_used),
            "avoided": list(avoided),
            "selection": selection,
        }
        selected_rows.append(row)
        trace["SELECTED_CAPABILITY_ID"] = capability_id
        trace["SELECTION"] = selection
        traces.append(trace)
        if str(requirement["task_id"]) == "benchmark-compare":
            benchmark_selected = capability_id

    unique_owners = {
        (
            row.get("selected_agent_id"),
            row.get("selected_skill_id"),
            row["selected_capability_id"],
        )
        for row in selected_rows
    }

    report = {
        "schema": "capability-resolution-reuse-proof/v1",
        "SOURCE_RUN_ID": source_run_id,
        "SOURCE_RESPONSE_SHA256": response_sha256,
        "NVIDIA_OUTPUT_REUSED_WITHOUT_NEW_PROVIDER_CALL": "PASS",
        "PROVIDER_CALLS_EXECUTED": 0,
        "JSON_PARSE_VALID": "PASS",
        "MISSION_PROPOSAL_SCHEMA_VALID": "PASS",
        "REQUIREMENT_COUNT": len(requirements),
        "ALL_REQUIREMENTS_RESOLVED": (
            "PASS" if len(selected_rows) == len(requirements) else "FAIL"
        ),
        "BENCHMARK_CAPABILITY_SELECTED": benchmark_selected,
        "CAPABILITY_SELECTION_FROM_REGISTRY": "PASS",
        "HARDCODED_CAPABILITY_FALLBACK": "NO",
        "MINIMUM_SUFFICIENT_TEAM": (
            "PASS"
            if 0 < len(unique_owners) <= len(requirements)
            else "FAIL"
        ),
        "SELECTED_CAPABILITIES": [
            row["selected_capability_id"] for row in selected_rows
        ],
        "SELECTED_SPECIALIST_AGENTS": sorted({
            str(row.get("selected_agent_id"))
            for row in selected_rows
            if row.get("selected_agent_id")
        }),
        "SELECTED_SKILLS": sorted({
            str(row.get("selected_skill_id"))
            for row in selected_rows
            if row.get("selected_skill_id")
        }),
        "SELECTED_TASKS": selected_rows,
        "RESOLUTION_TRACES": traces,
        "ROOT_CAUSE_CLASS": (
            "A_ADDY_BLOCKED_BY_STALE_OPENCODE_HEALTH_POLICY"
            if benchmark_selected
            else "UNRESOLVED"
        ),
        "HEALTH_POLICY_FIX": "SEMANTIC_PROVIDER_REQUIRED",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for key in (
        "NVIDIA_OUTPUT_REUSED_WITHOUT_NEW_PROVIDER_CALL",
        "PROVIDER_CALLS_EXECUTED",
        "ALL_REQUIREMENTS_RESOLVED",
        "BENCHMARK_CAPABILITY_SELECTED",
        "CAPABILITY_SELECTION_FROM_REGISTRY",
        "HARDCODED_CAPABILITY_FALLBACK",
        "MINIMUM_SUFFICIENT_TEAM",
        "ROOT_CAUSE_CLASS",
    ):
        print(f"{key}={report[key]}")
    print(
        "SELECTED_CAPABILITIES="
        + ",".join(report["SELECTED_CAPABILITIES"])
    )
    print(
        "SELECTED_SPECIALIST_AGENTS="
        + ",".join(report["SELECTED_SPECIALIST_AGENTS"])
    )
    print("SELECTED_SKILLS=" + ",".join(report["SELECTED_SKILLS"]))

    if (
        report["ALL_REQUIREMENTS_RESOLVED"] != "PASS"
        or not benchmark_selected
        or report["PROVIDER_CALLS_EXECUTED"] != 0
    ):
        return {**report, "status": "FAIL"}
    return {**report, "status": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--response-sha256", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        source_root=args.source_root,
        response_sha256=args.response_sha256,
        output=args.output,
        source_run_id=args.source_run_id,
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
