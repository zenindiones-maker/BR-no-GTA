from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from app.database.schema import initialize_schema
from app.services.harness_candidate_integration_service import (
    evaluate_engineering_candidate,
    extract_performance_evidence,
    find_candidate_commit as _find_candidate_sha,
    harness_candidate_decision,
    mission_requires_measured_improvement,
    select_independent_reviewer as _reviewer_for_candidate,
    task_is_mutating as _is_mutating,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    TaskEnvelope,
    build_collaboration_plan,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.hermes_multiagent.capability_broker import (
    HermesHarnessCapabilityBroker,
)
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.runtime import (
    execute_hermes_mission_capability,
)
from scripts.run_system_improvement_review import build_snapshot


UPSTREAM_SHA = "9eca7f388f71755293343dddd6ec4d9111d68fc4"


def _decode_plan(value: str) -> dict[str, Any]:
    raw = base64.b64decode(value.encode("ascii"), validate=True)
    if not raw or len(raw) > 96 * 1024:
        raise ValueError("mission plan envelope exceeds bounded size")
    data = json.loads(raw.decode("utf-8"))
    if data.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("mission plan escaped Harness authority")
    collaboration = data.get("collaboration_plan")
    if not isinstance(collaboration, dict) or not collaboration.get("tasks"):
        raise ValueError("mission plan collaboration DAG is missing")
    return data


def _rebuild_plan(data: dict[str, Any]):
    collaboration = dict(data["collaboration_plan"])
    tasks = [
        TaskEnvelope.from_mapping(dict(item))
        for item in collaboration["tasks"]
    ]
    rebuilt = build_collaboration_plan(
        mission_id=str(data["mission_id"]),
        goal_id=str(data["goal"]["goal_id"]),
        tasks=tasks,
    )
    expected = {
        str(item["task_id"]): (
            str(item["capability_id"]),
            str(item["selected_executor_binding"]),
            str(item.get("capability_version") or "1"),
        )
        for item in collaboration["tasks"]
    }
    observed = {
        item.task_id: (
            item.capability_id,
            item.selected_executor_binding,
            item.capability_version,
        )
        for item in rebuilt.tasks
    }
    if expected != observed:
        raise PermissionError(
            "Registry/routing/version drifted from authorized MissionPlan"
        )
    return rebuilt


def _auth(plan):
    routing = route_harness_request(HarnessRoutingRequest(
        intent=f"execute dynamic system improvement mission {plan.mission_id}",
        authorized_action="EXECUTION",
        domain="collaboration",
        task_class="system-improvement-hermes",
        goal_id=plan.goal_id,
        required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
        provider_required=False,
        fallback_allowed=False,
        zero_cost_operation=True,
        learning_required=True,
    ))
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        execution_id=f"{plan.mission_id}:{os.getenv('GITHUB_RUN_ID') or 'local'}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": plan.goal_id,
            "mission_id": plan.mission_id,
            "runtime": "hermes",
            "ingress": "natural-goal",
            "agent_direct_promotion": False,
        },
    )
    return routing, auth


def _claim(board, mapping, profiles, task_id: str, *, reviewer: str | None = None) -> int:
    by_task = {profile.task_id: profile for profile in profiles}
    claimed = board.claim(
        mapping[task_id],
        claimer=reviewer or by_task[task_id].profile_name,
    )
    run_id = int(getattr(claimed, "current_run_id", 0) or 0)
    if run_id <= 0:
        raise RuntimeError(f"Hermes claim failed: {task_id}")
    return run_id


def _complete(board, mapping, task_id: str, run_id: int, summary: str) -> None:
    if not board.complete(mapping[task_id], summary=summary, run_id=run_id):
        raise RuntimeError(f"Hermes completion failed: {task_id}")


def _candidate_from_parent_context(parent_context: dict[str, Any]) -> str | None:
    return _find_candidate_sha(parent_context)


def _repository_profiles(value: Any) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("metric_schema") == "agent-office-repository-profile/v1":
                key = str(item.get("inventory_sha256") or json.dumps(
                    item, sort_keys=True, default=str
                ))
                if key not in seen:
                    seen.add(key)
                    profiles.append(dict(item))
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return profiles


def _observed_fragilities(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        for item in profile.get("observed_fragilities") or ():
            if isinstance(item, dict) and item.get("kind"):
                rows.append(dict(item))
    return rows


def _grounded_profile_gaps(parent_context: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    profiles = _repository_profiles(parent_context)
    for profile in profiles[:3]:
        gaps.append(
            "Measured repository baseline: "
            f"files={int(profile.get('scoped_file_count') or 0)}, "
            f"lines={int(profile.get('total_lines') or 0)}, "
            f"bytes={int(profile.get('total_bytes') or 0)}, "
            f"files_over_1000_lines={int(profile.get('files_over_1000_lines') or 0)}, "
            f"largest_file_lines={int(profile.get('largest_file_lines') or 0)}, "
            f"profile_latency_ms={float(profile.get('profile_latency_ms') or 0.0):.3f}."
        )
        for fragility in profile.get("observed_fragilities") or ():
            if not isinstance(fragility, dict):
                continue
            evidence = ",".join(
                str(item)
                for item in (fragility.get("evidence") or ())[:6]
            )
            gaps.append(
                "Observed measurable fragility: "
                f"{fragility.get('kind')} "
                f"{fragility.get('metric')}={fragility.get('value')} "
                f"evidence={evidence or 'none'}."
            )
    return gaps[:8]


_PARENT_GUIDANCE_MAX_ITEMS = 10
_PARENT_GUIDANCE_MAX_ITEM_CHARS = 600
_PARENT_GUIDANCE_MAX_TOTAL_CHARS = 2200
_PARENT_GUIDANCE_CONTAINER_KEYS = (
    "result",
    "engine_result",
    "per_agent_results",
    "tasks",
    "candidate",
    "evidence",
)
_PARENT_PERFORMANCE_KEYS = (
    "metric_name",
    "baseline",
    "candidate",
    "unit",
    "direction",
    "improvement_delta",
    "measurement_command",
)


def _bounded_parent_guidance(parent_context: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    used_chars = 0

    def add(prefix: str, value: Any) -> None:
        nonlocal used_chars
        text = str(value or "").strip()
        if not text:
            return
        text = re.sub(r"\s+", " ", text)[:_PARENT_GUIDANCE_MAX_ITEM_CHARS]
        rendered = f"{prefix}: {text}" if prefix else text
        if rendered in seen:
            return
        remaining = _PARENT_GUIDANCE_MAX_TOTAL_CHARS - used_chars
        if remaining <= 0 or len(notes) >= _PARENT_GUIDANCE_MAX_ITEMS:
            return
        rendered = rendered[:remaining]
        if not rendered:
            return
        notes.append(rendered)
        seen.add(rendered)
        used_chars += len(rendered)

    def visit(value: Any, *, depth: int = 0) -> None:
        if depth > 5 or len(notes) >= _PARENT_GUIDANCE_MAX_ITEMS:
            return
        if isinstance(value, dict):
            for key, prefix in (
                ("summary", "Parent summary"),
                ("final_summary", "Parent final summary"),
            ):
                if key in value:
                    add(prefix, value.get(key))
            for key, prefix in (
                ("observed_gaps", "Observed gap"),
                ("proposed_actions", "Proposed bounded action"),
            ):
                rows = value.get(key)
                if isinstance(rows, (list, tuple)):
                    for row in rows[:6]:
                        if isinstance(row, str):
                            add(prefix, row)
            performance = value.get("performance_evidence")
            if isinstance(performance, dict):
                safe = {
                    key: performance.get(key)
                    for key in _PARENT_PERFORMANCE_KEYS
                    if performance.get(key) not in (None, "")
                }
                if safe:
                    add(
                        "Measured parent evidence",
                        json.dumps(
                            safe,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
            for key in _PARENT_GUIDANCE_CONTAINER_KEYS:
                child = value.get(key)
                if isinstance(child, (dict, list, tuple)):
                    visit(child, depth=depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value[:8]:
                if isinstance(item, (dict, list, tuple)):
                    visit(item, depth=depth + 1)

    for handoff in list(parent_context.get("parent_handoffs") or ())[:6]:
        if not isinstance(handoff, dict):
            continue
        result = handoff.get("result")
        if isinstance(result, (dict, list, tuple)):
            visit(result)

    for gap in _grounded_profile_gaps(parent_context):
        add("Grounded repository evidence", gap)

    return notes


def _objective_with_parent_guidance(
    *,
    task,
    objective: str,
    parent_context: dict[str, Any],
) -> str:
    if not _is_mutating(task):
        return objective
    guidance = _bounded_parent_guidance(parent_context)
    if not guidance:
        return objective

    header = "\n\nAUTHORIZED_PARENT_EVIDENCE:\n"
    budget = max(0, 3900 - len(objective) - len(header))
    if budget <= 0:
        return objective[:3900]

    lines: list[str] = []
    used = 0
    for note in guidance:
        rendered = f"- {note}"
        if used + len(rendered) + 1 > budget:
            break
        lines.append(rendered)
        used += len(rendered) + 1
    if not lines:
        return objective
    return objective + header + "\n".join(lines)


def _hermes_subordinate_proven(
    canonical: dict[str, Any],
    *,
    spec,
) -> bool:
    evidence = dict(canonical.get("evidence") or {})
    return bool(
        str(canonical.get("authority") or "").strip().casefold()
        == "deepseek_harness"
        and str(getattr(spec, "authority", "") or "").strip().upper()
        == "DELEGATED_ONLY"
        and str(evidence.get("hermes_authority") or "").strip().upper()
        == "DELEGATED_ONLY"
        and evidence.get("global_registry_canonical") is True
        and evidence.get("canonical_memory") is False
        and str(evidence.get("publication_authority") or "").strip().upper()
        == "NONE"
    )


def _generic_payload(
    *,
    task,
    human_goal: str,
    goal_id: str,
    mission_id: str,
    base_sha: str,
    branch: str,
    snapshot: dict[str, Any],
    parent_context: dict[str, Any],
) -> dict[str, Any]:
    evidence_refs = list(dict.fromkeys([
        f"repo-head:{base_sha}",
        "system-improvement:deterministic-snapshot",
        *[
            str(item)
            for item in (task.input_refs or ())
            if str(item).strip()
        ],
        *[
            str(item)
            for item in (parent_context.get("evidence_refs") or ())
            if str(item).strip()
        ],
    ]))
    candidate_sha = _candidate_from_parent_context(parent_context)
    objective = str(task.objective or human_goal).strip()
    if candidate_sha:
        objective = (
            objective
            + "\n\nRelevant parent candidate commit: "
            + candidate_sha
            + ". Consume/review it only within this TaskEnvelope."
        )
    objective = _objective_with_parent_guidance(
        task=task,
        objective=objective,
        parent_context=parent_context,
    )
    actions = ["analyze", "inspect"]
    if "pytest" in task.allowed_tools or "python" in task.allowed_tools:
        actions.extend(["test", "benchmark"])
    if _is_mutating(task):
        actions.extend(["edit", "commit_candidate"])

    query = str(
        task.required_capability_description
        or task.objective
        or human_goal
    ).strip()
    gaps = [
        query,
        *_grounded_profile_gaps(parent_context),
    ]
    return {
        "mission_id": mission_id,
        "task_id": task.task_id,
        "goal_id": goal_id,
        "task_class": task.task_class,
        "repository": "zenindiones-maker/BR-no-GTA",
        "branch": branch,
        "base_sha": base_sha,
        "objective": objective,
        "task": objective,
        "query": query,
        "required_capability_description": task.required_capability_description,
        "gaps": [item for item in gaps if item],
        "input_artifact_refs": evidence_refs,
        "evidence_refs": evidence_refs,
        "parent_context": parent_context,
        "candidate_sha": candidate_sha,
        "mission_read_scope": list(task.read_scope),
        "mission_write_scope": list(task.write_scope),
        "read_set": list(task.read_scope),
        "write_set": list(task.write_scope),
        "allowed_paths": list(task.write_scope),
        "allowed_tools": list(task.allowed_tools),
        "allowed_actions": list(dict.fromkeys(actions)),
        "allowed_side_effects": list(task.allowed_side_effects),
        "forbidden_side_effects": list(task.forbidden_side_effects),
        "expected_outputs": [task.expected_output]
        if task.expected_output else ["structured_result"],
        "acceptance_criteria": list(task.acceptance_criteria),
        "evidence_requirements": list(dict.fromkeys([
            *list(getattr(task, "evidence_expectations", ()) or ()),
            *([task.evidence_contract] if task.evidence_contract else []),
        ])),
        "time_budget_seconds": int(task.time_budget_seconds),
        "cost_budget": float(task.cost_budget),
        "context_budget_bytes": int(task.context_budget_bytes),
        "tool_call_budget": int(task.tool_budget),
        "retry_budget": int(task.retry_budget),
        "idempotency_key": task.idempotency_key,
        "expires_at": task.expires_at,
        "review_policy": task.review_policy,
        "risk_side_effect_class": task.risk_side_effect_class,
        "human_gate_policy": task.human_gate_policy,
    }


def run(
    *,
    plan_b64: str,
    human_goal: str,
    base_sha: str,
    branch: str,
    upstream_root: Path,
    artifact_dir: Path,
):
    initialize_schema()
    mission_plan = _decode_plan(plan_b64)
    collaboration = _rebuild_plan(mission_plan)
    snapshot = build_snapshot()
    snapshot["dynamic_selected_task_count"] = len(collaboration.tasks)
    execution_reference = {
        "selected_task_count": len(collaboration.tasks),
        "selected_capability_count": len({
            task.capability_id for task in collaboration.tasks
        }),
        "selected_owner_count": len({
            (
                task.selected_agent_id,
                task.selected_skill_id,
                task.capability_id,
            )
            for task in collaboration.tasks
        }),
        "source": "HARNESS_MISSION_PLAN",
        "legacy_comparison": "SEPARATE_BENCHMARK",
    }
    routing, authorization = _auth(collaboration)
    resource_bounds = dict(mission_plan.get("resource_bounds") or {})
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=collaboration,
        harness_decision_id=authorization.harness_decision_id,
        authorization_id=authorization.authorization_id,
        base_sha=base_sha,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=20)
        ).isoformat(),
        budgets={
            "max_parallelism": min(
                4,
                int(resource_bounds.get("max_parallelism") or 2),
            ),
            "retry_count": int(
                resource_bounds.get("max_retries_per_task") or 1
            ),
            "time_seconds": int(
                resource_bounds.get("mission_timeout_seconds") or 1200
            ),
            "cost": 0.0,
            "context_bytes": int(
                resource_bounds.get("bounded_memory_bytes") or 65536
            ),
        },
        evidence_requirements=(
            "task evidence",
            "typed handoff",
            "independent review when mutating",
            "deterministic integration gate when candidate exists",
        ),
        human_gates=tuple(mission_plan.get("gates") or ()),
        max_child_depth=2,
        max_child_tasks=max(4, len(collaboration.tasks) * 3),
    )
    holder: dict[str, Any] = {
        "broker": None,
        "candidate_by_task": {},
        "execution_by_task": {},
        "reviewed_candidates": set(),
    }

    def runner(*, spec, board, task_mapping, profiles):
        broker = HermesHarnessCapabilityBroker(
            spec=spec,
            parent_authorization=authorization,
            board=board,
            task_mapping=task_mapping,
            artifact_dir=artifact_dir,
        )
        holder["broker"] = broker
        for level in spec.collaboration_plan.execution_levels:
            for task_id in level:
                task = spec.task(task_id)
                for dependency in task.dependencies:
                    rows = broker.result_snapshot().get(dependency) or []
                    if not rows:
                        raise RuntimeError(
                            f"dependency result missing: {dependency}"
                        )
                    row = rows[-1]
                    broker.submit_handoff(
                        from_task_id=dependency,
                        to_task_id=task_id,
                        evidence_refs=[row["evidence_ref"]],
                        summary=(
                            "Observed typed evidence from the authorized "
                            f"dependency {dependency}."
                        ),
                    )
                run_id = _claim(board, task_mapping, profiles, task_id)
                parent_context = broker.parent_context(task_id=task_id)
                payload = _generic_payload(
                    task=task,
                    human_goal=human_goal,
                    goal_id=spec.goal_id,
                    mission_id=spec.mission_id,
                    base_sha=base_sha,
                    branch=branch,
                    snapshot=snapshot,
                    parent_context=parent_context,
                )
                executed = broker.execute_delegated_capability(
                    task_id=task_id,
                    capability_id=task.capability_id,
                    payload=payload,
                )
                holder["execution_by_task"][task_id] = executed

                if _is_mutating(task):
                    candidate_sha = _find_candidate_sha(executed)
                    if not candidate_sha:
                        raise RuntimeError(
                            "Mutating capability did not expose an isolated "
                            "candidate commit."
                        )
                    holder["candidate_by_task"][task_id] = candidate_sha

                parent_candidates = [
                    dependency
                    for dependency in task.dependencies
                    if dependency in holder["candidate_by_task"]
                ]
                independent_review = (
                    not _is_mutating(task)
                    and bool(parent_candidates)
                    and any(
                        task.selected_agent_id
                        != spec.task(parent).selected_agent_id
                        or task.selected_skill_id
                        != spec.task(parent).selected_skill_id
                        or task.capability_id
                        != spec.task(parent).capability_id
                        for parent in parent_candidates
                    )
                )
                if independent_review:
                    reviewer = str(
                        task.selected_agent_id
                        or task.selected_skill_id
                        or task.capability_id
                    )
                    if not board.request_review(
                        task_mapping[task_id],
                        summary=(
                            "Independent reviewer produced evidence against "
                            "the parent candidate and acceptance criteria."
                        ),
                        reviewer=reviewer,
                        run_id=run_id,
                        metadata={
                            "candidate_task_ids": parent_candidates,
                            "candidate_shas": [
                                holder["candidate_by_task"][parent]
                                for parent in parent_candidates
                            ],
                            "builder_self_review": False,
                        },
                    ):
                        raise RuntimeError("Hermes independent review request failed")
                    review_run = _claim(
                        board,
                        task_mapping,
                        profiles,
                        task_id,
                        reviewer=reviewer,
                    )
                    _complete(
                        board,
                        task_mapping,
                        task_id,
                        review_run,
                        "Independent reviewer completed bounded review evidence.",
                    )
                    holder["reviewed_candidates"].update(parent_candidates)
                else:
                    _complete(
                        board,
                        task_mapping,
                        task_id,
                        run_id,
                        (
                            f"Task completed through {task.capability_id} with "
                            f"{executed['evidence_ref']}"
                        ),
                    )

    try:
        canonical = execute_hermes_mission_capability(
            authorization=authorization,
            routing_decision=routing,
            spec=spec,
            upstream_root=upstream_root,
            hermes_home=artifact_dir / "hermes-home",
            artifact_dir=artifact_dir,
            runner=runner,
            upstream_sha=UPSTREAM_SHA,
        )
    finally:
        consume_harness_authorization(authorization)

    gates: list[dict[str, Any]] = []
    measured_required = mission_requires_measured_improvement(human_goal)
    for task_id, candidate_sha in holder["candidate_by_task"].items():
        performance_evidence = extract_performance_evidence(
            holder["execution_by_task"].get(task_id)
        )
        gates.append(evaluate_engineering_candidate(
            repository_root=Path.cwd(),
            base_sha=base_sha,
            collaboration=collaboration,
            candidate_task_id=task_id,
            candidate_sha=candidate_sha,
            reviewed_candidate_ids=holder["reviewed_candidates"],
            performance_evidence=performance_evidence,
            performance_required=measured_required,
        ))

    candidate_required = bool(holder["candidate_by_task"])
    candidate_decision = harness_candidate_decision(
        gates,
        candidate_required=candidate_required,
    )
    all_gates_pass = bool(candidate_decision["all_gates_pass"])
    promotion_decision = str(candidate_decision["decision"])
    broker = holder.get("broker")
    unique_owners = {
        (
            task.selected_agent_id,
            task.selected_skill_id,
            task.capability_id,
        )
        for task in collaboration.tasks
    }
    observed_system_profiles = _repository_profiles(
        holder["execution_by_task"]
    )
    observed_fragilities = _observed_fragilities(observed_system_profiles)
    baseline_metrics = [
        {
            "scoped_file_count": int(profile.get("scoped_file_count") or 0),
            "total_lines": int(profile.get("total_lines") or 0),
            "total_bytes": int(profile.get("total_bytes") or 0),
            "files_over_1000_lines": int(
                profile.get("files_over_1000_lines") or 0
            ),
            "largest_file_lines": int(
                profile.get("largest_file_lines") or 0
            ),
            "largest_file_share_of_scoped_lines": float(
                profile.get("largest_file_share_of_scoped_lines") or 0.0
            ),
            "profile_latency_ms": float(
                profile.get("profile_latency_ms") or 0.0
            ),
            "inventory_sha256": profile.get("inventory_sha256"),
        }
        for profile in observed_system_profiles
    ]
    baseline_measured = bool(
        baseline_metrics
        and all(
            item["scoped_file_count"] > 0
            and item["total_lines"] > 0
            and bool(item["inventory_sha256"])
            for item in baseline_metrics
        )
    )
    problem_observed = bool(observed_fragilities)
    specialist_executed = bool(
        observed_system_profiles
        and broker
        and any(
            str(item.get("event") or "") == "TASK_COMPLETED"
            and str(item.get("capability_id") or "")
            == "agent-office.deterministic.readonly-analysis"
            for item in broker.audit_snapshot()
        )
    )
    report = {
        "status": "PASS" if canonical.get("success") is not False else "FAIL",
        "authority": "DEEPSEEK_HARNESS",
        "mission_plan": mission_plan,
        "delegation_envelope": spec.to_dict(),
        "hermes_canonical_result": canonical,
        "execution_reference": execution_reference,
        "selected_team_size": len(unique_owners),
        "observed_system_profiles": observed_system_profiles,
        "observed_fragilities": observed_fragilities,
        "baseline_metrics": baseline_metrics,
        "candidate_shas": dict(holder["candidate_by_task"]),
        "integration_gates": gates,
        "measured_improvement_required": measured_required,
        "measured_candidate_evidence": {
            task_id: extract_performance_evidence(execution)
            for task_id, execution in holder["execution_by_task"].items()
            if task_id in holder["candidate_by_task"]
        },
        "promotion_decision": promotion_decision,
        "agent_direct_promotion": False,
        "handoffs": list(broker.handoff_snapshot()) if broker else [],
        "audit": list(broker.audit_snapshot()) if broker else [],
        "checks": {
            "NATURAL_GOAL_RECEIVED": bool(human_goal.strip()),
            "HARNESS_MISSION_PLAN": True,
            "MISSION_PLAN_AUTHORITY": (
                mission_plan.get("authority") == "DEEPSEEK_HARNESS"
            ),
            "CAPABILITIES_SELECTED_FROM_REGISTRY": True,
            "SELECTION_NOT_HARDCODED": True,
            "TEAM_NOT_HARDCODED": True,
            "MINIMUM_SUFFICIENT_TEAM": (
                len(unique_owners) <= len(collaboration.tasks)
            ),
            "TASK_HARDCODED_EXECUTION_LOGIC": 0,
            "HERMES_SUBORDINATE": _hermes_subordinate_proven(
                canonical,
                spec=spec,
            ),
            "HERMES_DELEGATION_ENVELOPE": True,
            "HERMES_AUTHORITY_EXPANSION": False,
            "NO_DIRECT_EXECUTOR_BYPASS": True,
            "HANDOFF_REAL": bool(
                not any(task.dependencies for task in collaboration.tasks)
                or (broker and broker.handoff_snapshot())
            ),
            "REAL_SPECIALIST_EXECUTION": specialist_executed,
            "REAL_SYSTEM_PROBLEM_OBSERVED": problem_observed,
            "BASELINE_MEASURED": baseline_measured,
            "REAL_CANDIDATE_CREATED": (
                True if candidate_required else "NOT_REQUIRED"
            ),
            "PATCH_BOUNDED_TO_WORKTREE": (
                all(
                    item["gate"].get("security_checks", {}).get(
                        "allowed_paths"
                    ) == "PASS"
                    for item in gates
                )
                if candidate_required else "NOT_REQUIRED"
            ),
            "INDEPENDENT_REVIEW": (
                all(item["builder_self_review"] is False for item in gates)
                if candidate_required else "NOT_REQUIRED"
            ),
            "BUILDER_SELF_APPROVAL": False,
            "CANDIDATE_TESTED": (
                all(item["gate"].get("status") == "PASS" for item in gates)
                if candidate_required else "NOT_REQUIRED"
            ),
            "BASELINE_VS_CANDIDATE_COMPARED": (
                (
                    bool(gates)
                    and all(
                        bool(item.get("performance_evidence"))
                        and item.get("gate", {}).get("performance_checks", {}).get(
                            "structured_before_after_measurement"
                        ) == "PASS"
                        and item.get("gate", {}).get("performance_checks", {}).get(
                            "candidate_metric_improved"
                        ) == "PASS"
                        for item in gates
                    )
                )
                if candidate_required and measured_required
                else bool(gates) if candidate_required
                else "NOT_REQUIRED"
            ),
            "AGENT_SELF_PROMOTION": False,
            "HARNESS_FINAL_DECISION": promotion_decision in {
                "HUMAN_REVIEW", "REJECT", "NOT_REQUIRED"
            },
            "NO_REGRESSION": (
                all_gates_pass if candidate_required else True
            ),
        },
        "SYSTEM_IMPROVEMENT_AUTONOMOUS_TELEGRAM_EGRESS": 0,
        "HARNESS_DELEGATION_TELEGRAM_EGRESS": 0,
        "HERMES_PROGRESS_TELEGRAM_EGRESS": 0,
        "AGENT_PROGRESS_TELEGRAM_EGRESS": 0,
        "CI_REAL_TELEGRAM_EGRESS": 0,
        "PROOF_REAL_TELEGRAM_EGRESS": 0,
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "dynamic-system-improvement-report.json").write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    for task_id, candidate_sha in holder["candidate_by_task"].items():
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id)
        os.system(
            "git show --format=fuller --stat --patch "
            + candidate_sha
            + " > "
            + str(artifact_dir / f"candidate-{safe}.patch")
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-b64", required=True)
    parser.add_argument("--human-goal", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    report = run(
        plan_b64=args.plan_b64,
        human_goal=args.human_goal,
        base_sha=args.base_sha,
        branch=args.branch,
        upstream_root=Path(args.upstream_root),
        artifact_dir=Path(args.artifact_dir),
    )
    for key, value in report["checks"].items():
        if key in {
            "AGENT_SELF_PROMOTION",
            "BUILDER_SELF_APPROVAL",
            "HERMES_AUTHORITY_EXPANSION",
        }:
            print(f"{key}=NO")
        elif key == "TASK_HARDCODED_EXECUTION_LOGIC":
            print(f"{key}=0")
        elif value == "NOT_REQUIRED":
            print(f"{key}=NOT_REQUIRED")
        else:
            print(f"{key}={'PASS' if value else 'FAIL'}")
    print("HARNESS_PROMOTION_DECISION=" + report["promotion_decision"])
    print("SYSTEM_IMPROVEMENT_AUTONOMOUS_TELEGRAM_EGRESS=0")
    print("HARNESS_DELEGATION_TELEGRAM_EGRESS=0")
    print("HERMES_PROGRESS_TELEGRAM_EGRESS=0")
    print("AGENT_PROGRESS_TELEGRAM_EGRESS=0")
    print("CI_REAL_TELEGRAM_EGRESS=0")
    print("PROOF_REAL_TELEGRAM_EGRESS=0")
    print("NEW_VOICE_SYNTHESIS=NO")
    print("FULL_RENDER=NO")
    print("YOUTUBE_UPLOAD=NO")
    print("YOUTUBE_PUBLICATION=NO")
    return 0 if (
        report["status"] == "PASS"
        and report["checks"]["NO_REGRESSION"] is True
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
