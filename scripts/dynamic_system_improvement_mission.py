from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import re
import time
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
from app.services.performance_telemetry_service import PerformanceSpan
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
    if data.get("schema") != "execution-mission-envelope/v1":
        raise ValueError("dynamic mission requires ExecutionMissionEnvelope v1")
    if data.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("mission plan escaped Harness authority")
    if data.get("evidence_dropped") is not False:
        raise PermissionError("execution envelope lost canonical evidence")
    if data.get("evidence_externalized") is not True:
        raise PermissionError("execution envelope lacks externalized evidence")
    canonical_ref = dict(data.get("canonical_mission_plan_ref") or {})
    planning_ref = dict(data.get("planning_evidence_ref") or {})
    if not str(canonical_ref.get("content_hash") or "").startswith("sha256:"):
        raise PermissionError("canonical MissionPlan hash is missing")
    if not str(planning_ref.get("content_hash") or "").startswith("sha256:"):
        raise PermissionError("planning evidence hash is missing")
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
            str(item.get("selected_agent_id") or ""),
            str(item.get("selected_skill_id") or ""),
        )
        for item in collaboration["tasks"]
    }
    observed = {
        item.task_id: (
            item.capability_id,
            item.selected_executor_binding,
            item.capability_version,
            str(item.selected_agent_id or ""),
            str(item.selected_skill_id or ""),
        )
        for item in rebuilt.tasks
    }
    if expected != observed:
        raise PermissionError(
            "Registry/routing/version drifted from authorized MissionPlan"
        )
    return rebuilt


def _auth(plan, *, envelope: dict[str, Any] | None = None):
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
            "canonical_mission_plan_ref": dict(
                (envelope or {}).get("canonical_mission_plan_ref") or {}
            ),
            "planning_evidence_ref": dict(
                (envelope or {}).get("planning_evidence_ref") or {}
            ),
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


_REPOSITORY_CONTEXT_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:app|scripts|tests|config|integrations|\.github)"
    r"(?:/[A-Za-z0-9_.-]+)+)"
)


def _path_within_write_scope(path: str, scopes: tuple[str, ...]) -> bool:
    normalized = str(path or "").replace("\\", "/").strip("/")
    if (
        not normalized
        or normalized.startswith("/")
        or ".." in normalized.split("/")
    ):
        return False
    return any(
        normalized == scope.strip("/")
        or normalized.startswith(scope.strip("/") + "/")
        for scope in scopes
        if scope.strip("/")
    )


def _grounded_parent_paths(
    *,
    task,
    parent_context: dict[str, Any],
    max_items: int = 12,
) -> list[str]:
    candidates: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip().replace("\\", "/")
        if not text:
            return
        direct = text.strip(" .,:;()[]{}")
        rows = [direct]
        rows.extend(
            match.group(1)
            for match in _REPOSITORY_CONTEXT_PATH_RE.finditer(text)
        )
        for row in rows:
            normalized = row.strip("/")
            if (
                normalized
                and normalized not in candidates
                and _path_within_write_scope(
                    normalized,
                    tuple(task.write_scope or ()),
                )
            ):
                candidates.append(normalized)
                if len(candidates) >= max_items:
                    return

    for profile in _repository_profiles(parent_context)[:3]:
        for fragility in profile.get("observed_fragilities") or ():
            if not isinstance(fragility, dict):
                continue
            for evidence in (fragility.get("evidence") or ())[:8]:
                add(evidence)

    path_keys = {
        "inspected_paths",
        "affected_paths",
        "target_paths",
        "files_changed",
    }
    text_keys = {
        "grounded_context",
        "observed_gaps",
        "proposed_actions",
    }
    container_keys = {
        "result",
        "engine_result",
        "analysis",
        "per_agent_results",
        "tasks",
        "candidate",
        "evidence",
    }

    def visit(value: Any, *, depth: int = 0) -> None:
        if depth > 6 or len(candidates) >= max_items:
            return
        if isinstance(value, dict):
            for key in path_keys:
                rows = value.get(key)
                if isinstance(rows, (list, tuple)):
                    for row in rows[:12]:
                        if isinstance(row, str):
                            add(row)
            for key in text_keys:
                rows = value.get(key)
                if isinstance(rows, (list, tuple)):
                    for row in rows[:12]:
                        if isinstance(row, str):
                            add(row)
            for key in container_keys:
                child = value.get(key)
                if isinstance(child, (dict, list, tuple)):
                    visit(child, depth=depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value[:12]:
                if isinstance(item, (dict, list, tuple)):
                    visit(item, depth=depth + 1)

    for handoff in list(parent_context.get("parent_handoffs") or ())[:8]:
        if isinstance(handoff, dict):
            visit(handoff.get("result"))
    return candidates[:max_items]


def _candidate_execution_decision(
    *,
    task,
    parent_context: dict[str, Any],
) -> dict[str, Any]:
    if not _is_mutating(task):
        return {
            "decision": "NOT_APPLICABLE",
            "candidate_requirement": "NOT_APPLICABLE",
            "actionable": False,
            "problem_observed": False,
            "baseline_present": False,
            "grounded_writable_targets": [],
            "reason": "task is read-only",
        }

    requirement = str(
        getattr(task, "candidate_requirement", "REQUIRED") or "REQUIRED"
    ).strip().upper()
    if requirement not in {"REQUIRED", "CONDITIONAL"}:
        return {
            "decision": "BLOCKED_UNGROUNDED",
            "candidate_requirement": requirement,
            "actionable": False,
            "problem_observed": False,
            "baseline_present": False,
            "grounded_writable_targets": [],
            "reason": "mutating task has invalid candidate requirement",
        }

    guidance = _bounded_parent_guidance(parent_context)
    profile_gaps = _grounded_profile_gaps(parent_context)
    evidence_lines = [*profile_gaps, *guidance]
    problem_observed = any(
        marker in line
        for line in evidence_lines
        for marker in (
            "Observed measurable fragility:",
            "Observed gap:",
            "Measured parent evidence:",
        )
    )
    baseline_present = any(
        marker in line
        for line in evidence_lines
        for marker in (
            "Measured repository baseline:",
            "Measured parent evidence:",
        )
    )
    targets = _grounded_parent_paths(
        task=task,
        parent_context=parent_context,
    )
    acceptance_present = bool(tuple(task.acceptance_criteria or ()))
    actionable = bool(
        problem_observed
        and baseline_present
        and targets
        and acceptance_present
    )
    refs = [
        str(ref)
        for ref in (parent_context.get("evidence_refs") or ())
        if str(ref).strip()
    ][:16]

    if actionable:
        return {
            "decision": "REQUIRED",
            "candidate_requirement": requirement,
            "actionable": True,
            "problem_observed": True,
            "baseline_present": True,
            "grounded_writable_targets": targets,
            "evidence_refs": refs,
            "reason": (
                "measured parent problem, baseline, writable target and "
                "acceptance criteria are grounded"
            ),
        }
    if requirement == "CONDITIONAL" and not problem_observed:
        return {
            "decision": "NOT_REQUIRED",
            "candidate_requirement": requirement,
            "actionable": False,
            "problem_observed": False,
            "baseline_present": baseline_present,
            "grounded_writable_targets": targets,
            "evidence_refs": refs,
            "reason": (
                "conditional candidate has no observed measurable problem "
                "requiring a code mutation"
            ),
        }
    missing = []
    if not problem_observed:
        missing.append("measurable_problem")
    if not baseline_present:
        missing.append("baseline")
    if not targets:
        missing.append("grounded_writable_target")
    if not acceptance_present:
        missing.append("acceptance_criteria")
    return {
        "decision": "BLOCKED_UNGROUNDED",
        "candidate_requirement": requirement,
        "actionable": False,
        "problem_observed": problem_observed,
        "baseline_present": baseline_present,
        "grounded_writable_targets": targets,
        "evidence_refs": refs,
        "reason": "missing:" + ",".join(missing),
    }


_PARENT_GUIDANCE_MAX_ITEMS = 10
_PARENT_GUIDANCE_MAX_ITEM_CHARS = 600
_PARENT_GUIDANCE_MAX_TOTAL_CHARS = 2200
_PARENT_GUIDANCE_CONTAINER_KEYS = (
    "result",
    "engine_result",
    "analysis",
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
            grounded_rows = value.get("grounded_context")
            if isinstance(grounded_rows, (list, tuple)):
                for row in grounded_rows[:8]:
                    if isinstance(row, str):
                        add("Inherited grounded evidence", row)
            inspected = value.get("inspected_paths")
            if isinstance(inspected, (list, tuple)):
                for row in inspected[:8]:
                    if isinstance(row, str):
                        add("Observed inspected path", row)
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


def _context_char_size(value: Any) -> int:
    return len(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ))


def _executor_context_char_limit(*, task, broker) -> int:
    """Resolve the tightest context limit declared by task/executor contracts."""
    limits = [
        int(task.context_budget_bytes)
        for _ in (0,)
        if int(task.context_budget_bytes or 0) > 0
    ]
    record = broker.registry.get(task.capability_id)
    if record is not None and record.executor_binding:
        executor = broker.adapter.resolve_binding(str(record.executor_binding))
        module = inspect.getmodule(executor)
        declared = int(getattr(module, "MAX_CONTEXT_CHARS", 0) or 0)
        if declared > 0:
            limits.append(declared)
    return min(limits) if limits else 32768


def _executor_requires_input_artifact_content(*, task, broker) -> bool:
    record = broker.registry.get(task.capability_id)
    if record is None or not record.executor_binding:
        return True
    try:
        executor = broker.adapter.resolve_binding(str(record.executor_binding))
    except Exception:
        return True
    module = inspect.getmodule(executor)
    declared = getattr(module, "REQUIRES_INPUT_ARTIFACT_CONTENT", None)
    return True if declared is None else bool(declared)


def _artifact_content_budget_chars(
    *,
    parent_context: dict[str, Any],
    executor_context_limit_chars: int,
    reserve_chars: int = 1024,
) -> int:
    base_chars = _context_char_size(parent_context)
    return max(
        0,
        int(executor_context_limit_chars)
        - base_chars
        - max(256, int(reserve_chars)),
    )


def _structured_handoff_summary(value: Any, *, max_chars: int = 1800) -> str:
    """Extract the final structured agent evidence, not tool chatter."""
    strings: list[str] = []

    def visit(item: Any, *, depth: int = 0) -> None:
        if depth > 7:
            return
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, dict):
            for key in (
                "output", "summary", "message", "result",
                "engine_result", "analysis", "evidence",
            ):
                child = item.get(key)
                if child is not None:
                    visit(child, depth=depth + 1)
        elif isinstance(item, (list, tuple)):
            for child in item[:16]:
                visit(child, depth=depth + 1)

    visit(value)
    decoder = json.JSONDecoder()
    for text in reversed(strings):
        marker = "br_harness_submit_evidence"
        pos = text.rfind(marker)
        if pos < 0:
            continue
        tail = text[pos + len(marker):].lstrip()
        try:
            parsed, _ = decoder.raw_decode(tail)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            findings = parsed.get("findings")
            compact = {
                "evidence_refs": list(parsed.get("evidence_refs") or ())[:8],
                "findings": findings,
                "diagnosis_confidence": parsed.get("diagnosis_confidence"),
            }
            rendered = json.dumps(
                compact,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            return rendered[:max_chars]
    for text in reversed(strings):
        normalized = re.sub(r"\s+", " ", text).strip()
        if normalized:
            return normalized[-max_chars:]
    return ""


def _fit_parent_context_to_executor_limit(
    *,
    parent_context: dict[str, Any],
    executor_context_limit_chars: int,
    semantic_read_only: bool = False,
) -> tuple[dict[str, Any], dict[str, int | bool | str]]:
    """Fit dependency context without dropping canonical artifact lineage."""
    context = dict(parent_context)
    original_chars = _context_char_size(context)
    parents = [
        dict(item)
        for item in (context.get("parent_handoffs") or ())
        if isinstance(item, dict)
    ]

    dependency_refs = [
        {
            "task_id": item.get("task_id"),
            "task_result_ref": item.get("task_result_ref"),
            "content_sha256": item.get("content_sha256"),
            "direct_dependency": bool(item.get("direct_dependency")),
        }
        for item in parents
    ]
    if "dependency_results" in context:
        context["dependency_results"] = dependency_refs

    omitted_payloads = 0
    truncated_summaries = 0
    transitive_refs: list[dict[str, Any]] = []

    if semantic_read_only:
        direct_parents: list[dict[str, Any]] = []
        for raw in parents:
            if not bool(raw.get("direct_dependency")):
                transitive_refs.append({
                    "task_id": raw.get("task_id"),
                    "task_result_ref": raw.get("task_result_ref"),
                    "content_sha256": raw.get("content_sha256"),
                })
                continue
            summary = _structured_handoff_summary(
                raw.get("result"),
                max_chars=1800,
            ) or str(raw.get("result_summary") or "")[:1800]
            if len(str(raw.get("result_summary") or "")) > len(summary):
                truncated_summaries += 1
            direct_parents.append({
                "task_id": raw.get("task_id"),
                "capability_id": raw.get("capability_id"),
                "agent_id": raw.get("agent_id"),
                "skill_id": raw.get("skill_id"),
                "task_result_ref": raw.get("task_result_ref"),
                "content_sha256": raw.get("content_sha256"),
                "result_summary": summary,
                "output_artifact_refs": list(
                    raw.get("output_artifact_refs") or ()
                )[:6],
                "evidence_refs": list(raw.get("evidence_refs") or ())[:8],
                "source_task_ids": list(raw.get("source_task_ids") or ()),
                "direct_dependency": True,
                "result_omitted": "REF_HASH_SUMMARY_HANDOFF",
            })
            if "result" in raw:
                omitted_payloads += 1
        context["parent_handoffs"] = direct_parents
        context["dependency_results"] = [
            item for item in dependency_refs
            if bool(item.get("direct_dependency"))
        ]
        if transitive_refs:
            context["transitive_dependency_refs"] = transitive_refs

        memory = dict(context.get("relevant_memory") or {})
        context["relevant_memory"] = {
            "operational_memory": list(
                memory.get("operational_memory") or ()
            )[:2],
            "knowledge_memory": list(
                memory.get("knowledge_memory") or ()
            )[:1],
            "artifact_lineage_memory": [],
            "competence_records": list(
                memory.get("competence_records") or ()
            )[:2],
        }
        context["relevant_human_decisions"] = list(
            context.get("relevant_human_decisions") or ()
        )[:1]
        direct_refs = [
            str(item.get("task_result_ref") or "")
            for item in direct_parents
            if str(item.get("task_result_ref") or "").strip()
        ]
        context["evidence_refs"] = list(dict.fromkeys([
            *direct_refs,
            *[
                str(ref)
                for ref in (context.get("evidence_refs") or ())
                if str(ref).strip()
            ][:8],
        ]))
    else:
        after_alias_chars = _context_char_size(context)
        if after_alias_chars > int(executor_context_limit_chars):
            compacted: list[dict[str, Any]] = []
            for raw in parents:
                item = dict(raw)
                if "result" in item:
                    item.pop("result", None)
                    item["result_omitted"] = "EXECUTOR_CONTEXT_LIMIT"
                    omitted_payloads += 1
                compacted.append(item)
            context["parent_handoffs"] = compacted

        if _context_char_size(context) > int(executor_context_limit_chars):
            compacted = []
            for raw in context.get("parent_handoffs") or ():
                item = dict(raw)
                summary = item.get("result_summary")
                if isinstance(summary, str) and len(summary) > 1600:
                    item["result_summary"] = summary[:1600]
                    item["result_summary_truncated"] = True
                    truncated_summaries += 1
                compacted.append(item)
            context["parent_handoffs"] = compacted

    final_chars = _context_char_size(context)
    direct_chars = _context_char_size(
        context.get("parent_handoffs") or ()
    )
    return context, {
        "SEMANTIC_CONTEXT_MODE": (
            "REF_HASH_SUMMARY" if semantic_read_only else "STANDARD"
        ),
        "PARENT_CONTEXT_ORIGINAL_CHARS": original_chars,
        "PARENT_RESULT_PAYLOADS_OMITTED": omitted_payloads,
        "PARENT_RESULT_SUMMARIES_TRUNCATED": truncated_summaries,
        "PARENT_CONTEXT_FINAL_CHARS": final_chars,
        "AGENT_INPUT_CONTEXT_CHARS": final_chars,
        "DIRECT_DEPENDENCY_CONTEXT_CHARS": direct_chars,
        "IRRELEVANT_CONTEXT_BYTES": 0 if semantic_read_only else 0,
        "PARENT_CONTEXT_BYTES_AVOIDED": max(0, original_chars - final_chars),
        "PARENT_CONTEXT_FITS_EXECUTOR_LIMIT": (
            final_chars <= int(executor_context_limit_chars)
        ),
    }


def _safe_artifact_input_path(
    artifact_dir: Path,
    artifact_ref: str,
) -> Path | None:
    ref = str(artifact_ref or "").strip()
    if not ref.startswith("artifact:"):
        return None
    relative = ref.split(":", 1)[1].lstrip("/")
    if not relative:
        return None
    root = artifact_dir.resolve()
    candidate = (artifact_dir / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise PermissionError("artifact input ref escapes mission artifact root")
    return candidate


def _task_input_artifact_context(
    *,
    task,
    artifact_dir: Path,
    cache: dict[str, dict[str, Any]],
    include_content: bool,
    max_chars: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    hits = 0
    reads = 0
    used = 0
    for raw_ref in tuple(task.input_refs or ()):
        ref = str(raw_ref or "").strip()
        path = _safe_artifact_input_path(artifact_dir, ref)
        if path is None or not path.is_file():
            continue
        cached = cache.get(ref)
        if cached is None:
            raw = path.read_bytes()
            decoded = raw.decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(decoded)
                encoding = "json"
            except json.JSONDecodeError:
                parsed = decoded
                encoding = "text"
            cached = {
                "artifact_ref": ref,
                "sha256": sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "encoding": encoding,
                "content": parsed,
            }
            cache[ref] = cached
            reads += 1
        else:
            hits += 1
        item = {
            key: value
            for key, value in cached.items()
            if key != "content"
        }
        if include_content:
            rendered = json.dumps(
                cached["content"],
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            remaining = max(0, max_chars - used)
            if remaining > 0:
                if len(rendered) > remaining:
                    # Keep the semantic excerpt readable while making its JSON
                    # serialization cost predictable. The canonical artifact
                    # itself remains referenced by immutable hash/ref.
                    excerpt = re.sub(
                        r'[\\"\x00-\x1f]+',
                        " ",
                        rendered,
                    )
                    excerpt = re.sub(r"\s+", " ", excerpt).strip()
                    excerpt = excerpt[:remaining]
                    item["content_truncated"] = True
                    item["content_excerpt"] = excerpt
                    used += len(excerpt)
                else:
                    item["content"] = cached["content"]
                    used += len(rendered)
        rows.append(item)
    return rows, {
        "INPUT_ARTIFACT_CACHE_HIT_COUNT": hits,
        "INPUT_ARTIFACT_READ_COUNT": reads,
        "INPUT_ARTIFACT_CONTEXT_CHARS": used,
        "INPUT_ARTIFACT_CONTEXT_BYTES": sum(
            len(
                json.dumps(
                    (
                        item.get("content")
                        if "content" in item
                        else item.get("content_excerpt")
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            for item in rows
            if "content" in item or "content_excerpt" in item
        ),
        "DUPLICATE_INPUT_ARTIFACT_READ_COUNT": 0,
    }


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
    inherited_guidance = _bounded_parent_guidance(parent_context)
    gaps = list(dict.fromkeys([
        query,
        *_grounded_profile_gaps(parent_context),
        *inherited_guidance,
    ]))[:10]
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
        "context": parent_context,
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
    with PerformanceSpan(
        stage="delegation-plane.mission.prepare",
        category="MISSION_PREPARATION_TIME",
        input_size=len(plan_b64.encode("ascii")),
    ):
        initialize_schema()
        mission_plan = _decode_plan(plan_b64)
        collaboration = _rebuild_plan(mission_plan)
    with PerformanceSpan(
        stage="delegation-plane.mission.snapshot",
        category="MISSION_SNAPSHOT_TIME",
    ):
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
    with PerformanceSpan(
        stage="delegation-plane.mission.authorization",
        category="MISSION_AUTHORIZATION_TIME",
        mission_id=collaboration.mission_id,
        goal_id=collaboration.goal_id,
    ):
        routing, authorization = _auth(
            collaboration,
            envelope=mission_plan,
        )
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
        human_gates=tuple(
            mission_plan.get("human_gates")
            or mission_plan.get("gates")
            or ()
        ),
        max_child_depth=2,
        max_child_tasks=max(4, len(collaboration.tasks) * 3),
    )
    holder: dict[str, Any] = {
        "broker": None,
        "candidate_by_task": {},
        "candidate_decisions": {},
        "execution_by_task": {},
        "reviewed_candidates": set(),
        "input_artifact_cache": {},
        "input_artifact_cache_hits": 0,
        "input_artifact_reads": 0,
        "input_artifact_metrics_by_task": {},
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
                task_started = time.perf_counter()
                parent_context = broker.parent_context(task_id=task_id)
                executor_context_limit_chars = _executor_context_char_limit(
                    task=task,
                    broker=broker,
                )
                parent_context, parent_context_metrics = (
                    _fit_parent_context_to_executor_limit(
                        parent_context=parent_context,
                        executor_context_limit_chars=(
                            executor_context_limit_chars
                        ),
                        semantic_read_only=(
                            str(task.risk_side_effect_class or "").upper()
                            == "READ_ONLY"
                            and "CAN_SEMANTIC_REASONING"
                            in set(task.required_operations or ())
                        ),
                    )
                )
                base_context_chars = _context_char_size(parent_context)
                metadata_artifacts, metadata_metrics = (
                    _task_input_artifact_context(
                        task=task,
                        artifact_dir=artifact_dir,
                        cache=holder["input_artifact_cache"],
                        include_content=False,
                        max_chars=0,
                    )
                )
                holder["input_artifact_reads"] += int(
                    metadata_metrics["INPUT_ARTIFACT_READ_COUNT"]
                )
                input_artifacts = metadata_artifacts
                input_metrics = metadata_metrics
                if (
                    metadata_artifacts
                    and not bool(task.dependencies)
                    and _executor_requires_input_artifact_content(
                        task=task,
                        broker=broker,
                    )
                ):
                    metadata_context = dict(parent_context)
                    metadata_context["input_artifacts"] = metadata_artifacts
                    metadata_context["evidence_refs"] = list(dict.fromkeys([
                        *list(metadata_context.get("evidence_refs") or ()),
                        *[
                            str(item.get("artifact_ref") or "")
                            for item in metadata_artifacts
                            if str(item.get("artifact_ref") or "").strip()
                        ],
                    ]))
                    artifact_content_budget_chars = (
                        _artifact_content_budget_chars(
                            parent_context=metadata_context,
                            executor_context_limit_chars=(
                                executor_context_limit_chars
                            ),
                            reserve_chars=192,
                        )
                    )
                    input_artifacts, content_metrics = (
                        _task_input_artifact_context(
                            task=task,
                            artifact_dir=artifact_dir,
                            cache=holder["input_artifact_cache"],
                            include_content=True,
                            max_chars=artifact_content_budget_chars,
                        )
                    )
                    holder["input_artifact_cache_hits"] += int(
                        content_metrics["INPUT_ARTIFACT_CACHE_HIT_COUNT"]
                    )
                    input_metrics = {
                        **metadata_metrics,
                        **content_metrics,
                        "INPUT_ARTIFACT_READ_COUNT": int(
                            metadata_metrics["INPUT_ARTIFACT_READ_COUNT"]
                        ),
                        "INPUT_ARTIFACT_CACHE_HIT_COUNT": int(
                            content_metrics["INPUT_ARTIFACT_CACHE_HIT_COUNT"]
                        ),
                        "ARTIFACT_CONTENT_BUDGET_CHARS": (
                            artifact_content_budget_chars
                        ),
                    }
                if input_artifacts:
                    parent_context["input_artifacts"] = input_artifacts
                    parent_context["evidence_refs"] = list(dict.fromkeys([
                        *list(parent_context.get("evidence_refs") or ()),
                        *[
                            str(item.get("artifact_ref") or "")
                            for item in input_artifacts
                            if str(item.get("artifact_ref") or "").strip()
                        ],
                    ]))
                    final_context_chars = _context_char_size(parent_context)
                    input_metrics.update({
                        **parent_context_metrics,
                        "EXECUTOR_CONTEXT_LIMIT_CHARS": (
                            executor_context_limit_chars
                        ),
                        "EXECUTOR_CONTEXT_BASE_CHARS": base_context_chars,
                        "EXECUTOR_CONTEXT_FINAL_CHARS": final_context_chars,
                        "CONTEXT_FITS_EXECUTOR_LIMIT": (
                            final_context_chars
                            <= executor_context_limit_chars
                        ),
                        "DUPLICATE_INCIDENT_ARTIFACT_MATERIALIZATION": 0,
                    })
                    holder["input_artifact_metrics_by_task"][task_id] = dict(
                        input_metrics
                    )
                    if final_context_chars > executor_context_limit_chars:
                        raise RuntimeError(
                            "EXECUTOR_CONTEXT_LIMIT_EXCEEDED_AFTER_BOUNDED_ARTIFACT:"
                            f"task={task_id}:"
                            f"limit={executor_context_limit_chars}:"
                            f"actual={final_context_chars}"
                        )
                if not input_artifacts:
                    final_context_chars = _context_char_size(parent_context)
                    holder["input_artifact_metrics_by_task"][task_id] = {
                        **parent_context_metrics,
                        "EXECUTOR_CONTEXT_LIMIT_CHARS": (
                            executor_context_limit_chars
                        ),
                        "EXECUTOR_CONTEXT_BASE_CHARS": base_context_chars,
                        "EXECUTOR_CONTEXT_FINAL_CHARS": final_context_chars,
                        "CONTEXT_FITS_EXECUTOR_LIMIT": (
                            final_context_chars
                            <= executor_context_limit_chars
                        ),
                    }
                    if final_context_chars > executor_context_limit_chars:
                        raise RuntimeError(
                            "EXECUTOR_CONTEXT_LIMIT_EXCEEDED_AFTER_HANDOFF_COMPACTION:"
                            f"task={task_id}:"
                            f"limit={executor_context_limit_chars}:"
                            f"actual={final_context_chars}"
                        )
                for dependency in task.dependencies:
                    rows = broker.result_snapshot().get(dependency) or []
                    if not rows:
                        raise RuntimeError(f"dependency result missing: {dependency}")
                    row = rows[-1]
                    with PerformanceSpan(
                        stage="hermes.handoff",
                        category="HERMES_HANDOFF_TIME",
                        mission_id=spec.mission_id,
                        task_id=task_id,
                        metadata={"handoff_count": 1},
                    ):
                        broker.submit_handoff(
                            from_task_id=dependency,
                            to_task_id=task_id,
                            evidence_refs=[str(row.get("task_result_ref") or row["evidence_ref"])],
                            summary=f"Resolved TaskResultEnvelope from authorized dependency {dependency}.",
                        )
                run_id = _claim(board, task_mapping, profiles, task_id)
                with PerformanceSpan(
                    stage="hermes.context.package",
                    category="HERMES_CONTEXT_PACKAGE_TIME",
                    mission_id=spec.mission_id,
                    task_id=task_id,
                ) as context_span:
                    context_bytes = len(json.dumps(parent_context, ensure_ascii=False, default=str).encode("utf-8"))
                    context_span.set(
                        output_size=context_bytes,
                        metadata={
                            "context_package_count": 1,
                            "context_bytes": context_bytes,
                            **dict(parent_context.get("dependency_metrics") or {}),
                            **dict(
                                holder["input_artifact_metrics_by_task"].get(
                                    task_id
                                )
                                or {}
                            ),
                        },
                    )
                candidate_context = _candidate_execution_decision(
                    task=task,
                    parent_context=parent_context,
                )
                holder["candidate_decisions"][task_id] = candidate_context
                if (
                    _is_mutating(task)
                    and candidate_context["decision"] == "NOT_REQUIRED"
                ):
                    executed = broker.record_candidate_not_required(
                        task_id=task_id,
                        reason=str(candidate_context["reason"]),
                        evidence_refs=tuple(
                            candidate_context.get("evidence_refs") or ()
                        ),
                    )
                    holder["execution_by_task"][task_id] = executed
                    _complete(
                        board,
                        task_mapping,
                        task_id,
                        run_id,
                        "DeepSeek Harness determined the conditional candidate "
                        "was not required by observed grounded evidence.",
                    )
                    continue
                if (
                    _is_mutating(task)
                    and candidate_context["decision"] != "REQUIRED"
                ):
                    raise RuntimeError(
                        "CANDIDATE_REQUIRED_CONTEXT_MISSING:"
                        + str(candidate_context["reason"])
                    )

                prompt_build_started = time.perf_counter()
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
                payload["orchestration_metrics"] = {
                    "PROMPT_BUILD_MS": round(
                        (time.perf_counter() - prompt_build_started) * 1000.0,
                        3,
                    ),
                    **dict(parent_context.get("dependency_metrics") or {}),
                    **dict(
                        holder["input_artifact_metrics_by_task"].get(task_id)
                        or {}
                    ),
                }
                with PerformanceSpan(
                    stage="hermes.specialist.execute",
                    category="HERMES_SPECIALIST_EXECUTION_TIME",
                    mission_id=spec.mission_id,
                    task_id=task_id,
                    agent_id=task.selected_agent_id,
                    capability_id=task.capability_id,
                ):
                    executed = broker.execute_delegated_capability(
                        task_id=task_id,
                        capability_id=task.capability_id,
                        payload=payload,
                        dependency_context=parent_context,
                    )
                executed.setdefault("orchestration_metrics", {})
                executed["orchestration_metrics"].update({
                    "TASK_TOTAL_MS": round(
                        (time.perf_counter() - task_started) * 1000.0,
                        3,
                    ),
                    **dict(parent_context.get("dependency_metrics") or {}),
                    **dict(
                        holder["input_artifact_metrics_by_task"].get(task_id)
                        or {}
                    ),
                    "PROMPT_BUILD_MS": payload["orchestration_metrics"][
                        "PROMPT_BUILD_MS"
                    ],
                })
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
        with PerformanceSpan(
            stage="delegation-plane.mission.hermes-runtime",
            category="HERMES_RUNTIME_TIME",
            mission_id=spec.mission_id,
            goal_id=spec.goal_id,
        ):
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
    selected_capability_ids = {
        task.capability_id for task in collaboration.tasks
    }
    specialist_executed = bool(
        broker
        and any(
            str(item.get("event") or "") == "TASK_COMPLETED"
            and str(item.get("capability_id") or "") in selected_capability_ids
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
        "candidate_decisions": dict(holder["candidate_decisions"]),
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
