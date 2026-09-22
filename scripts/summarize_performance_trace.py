from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import urllib.request
from typing import Any


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _epoch_ms(value: str | None) -> float | None:
    parsed = _parse_time(value)
    return None if parsed is None else parsed.timestamp() * 1000.0


def _duration_ms(started: str | None, finished: str | None) -> float | None:
    a = _parse_time(started)
    b = _parse_time(finished)
    if a is None:
        return None
    if b is None:
        b = datetime.now(timezone.utc)
    return max(0.0, (b - a).total_seconds() * 1000.0)


def _union_ms(intervals: list[tuple[float, float]]) -> float:
    valid = sorted((a, b) for a, b in intervals if b > a)
    if not valid:
        return 0.0
    total = 0.0
    start, end = valid[0]
    for current_start, current_end in valid[1:]:
        if current_start <= end:
            end = max(end, current_end)
            continue
        total += end - start
        start, end = current_start, current_end
    return total + (end - start)


def _intersection(interval: tuple[float, float], outer: tuple[float, float]) -> tuple[float, float] | None:
    start = max(interval[0], outer[0])
    end = min(interval[1], outer[1])
    return (start, end) if end > start else None


def _github_job(run_id: str) -> dict[str, Any]:
    token = str(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    repo = str(os.getenv("GITHUB_REPOSITORY") or "").strip()
    if not token or repo.count("/") != 1 or not run_id:
        return {"available": False, "steps": []}
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BR-no-GTA-performance/2.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__, "steps": []}
    jobs = list(payload.get("jobs") or ())
    if not jobs:
        return {"available": False, "steps": []}
    job = jobs[0]
    started_at = job.get("started_at")
    completed_at = job.get("completed_at")
    created_at = job.get("created_at")
    observed_at = datetime.now(timezone.utc).isoformat()
    steps = []
    for step in job.get("steps") or ():
        effective_completed_at = step.get("completed_at")
        if not effective_completed_at and step.get("status") == "in_progress":
            effective_completed_at = observed_at
        steps.append({
            "name": step.get("name"),
            "status": step.get("status"),
            "conclusion": step.get("conclusion"),
            "started_at": step.get("started_at"),
            "completed_at": step.get("completed_at"),
            "effective_completed_at": effective_completed_at,
            "duration_ms": _duration_ms(step.get("started_at"), effective_completed_at),
        })
    return {
        "available": True,
        "job_id": job.get("id"),
        "created_at": created_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "queue_wait_ms": _duration_ms(created_at, started_at) or 0.0,
        "runner_elapsed_ms": _duration_ms(started_at, completed_at) or 0.0,
        "wall_clock_ms": _duration_ms(created_at, completed_at) or 0.0,
        "steps": steps,
    }


def _span_metrics(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    spans: list[dict[str, Any]] = []
    by_id = {
        str(event.get("span_id")): event
        for event in events
        if str(event.get("span_id") or "").strip()
    }
    child_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    intervals: list[tuple[float, float]] = []
    provider_intervals: list[tuple[float, float]] = []
    category_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for event in events:
        start = _epoch_ms(event.get("started_at"))
        end = _epoch_ms(event.get("finished_at"))
        if start is None or end is None or end <= start:
            continue
        interval = (start, end)
        intervals.append(interval)
        category_intervals[str(event.get("category") or "IDLE/UNKNOWN_TIME")].append(interval)
        if event.get("provider"):
            provider_intervals.append(interval)
        parent = str(event.get("parent_span_id") or "")
        span_id = str(event.get("span_id") or "")
        if parent and parent in by_id and parent != span_id:
            child_intervals[parent].append(interval)

    category_cumulative: dict[str, float] = defaultdict(float)
    cumulative_work_ms = 0.0
    for event in events:
        start = _epoch_ms(event.get("started_at"))
        end = _epoch_ms(event.get("finished_at"))
        if start is None or end is None or end <= start:
            continue
        inclusive = max(0.0, float(event.get("duration_ms") or (end - start)))
        span_id = str(event.get("span_id") or "")
        children = []
        for child in child_intervals.get(span_id, []):
            clipped = _intersection(child, (start, end))
            if clipped is not None:
                children.append(clipped)
        exclusive = max(0.0, inclusive - _union_ms(children))
        cumulative_work_ms += exclusive
        category_cumulative[str(event.get("category") or "IDLE/UNKNOWN_TIME")] += exclusive
        item = dict(event)
        item.setdefault("start", item.get("started_at"))
        item.setdefault("end", item.get("finished_at"))
        item.setdefault("attempt", item.get("attempt_count", 1))
        item.setdefault("cache_hit", None)
        item.setdefault("input_fingerprint", None)
        item.setdefault("output_artifact", None)
        item.setdefault("work_class", "NECESSARY")
        item["inclusive_ms"] = round(inclusive, 3)
        item["exclusive_ms"] = round(exclusive, 3)
        spans.append(item)

    return spans, {
        "trace_active_wall_ms": _union_ms(intervals),
        "trace_cumulative_work_ms": cumulative_work_ms,
        "provider_critical_path_ms": _union_ms(provider_intervals),
        "provider_cumulative_work_ms": sum(
            float(item.get("exclusive_ms") or 0.0)
            for item in spans if item.get("provider")
        ),
        "parallelism_saved_ms": max(0.0, cumulative_work_ms - _union_ms(intervals)),
        "category_critical_path_ms": {
            key: _union_ms(value) for key, value in sorted(category_intervals.items())
        },
        "category_cumulative_work_ms": dict(sorted(category_cumulative.items())),
    }


def _filtered_union_ms(
    spans: list[dict[str, Any]],
    predicate,
) -> float:
    intervals: list[tuple[float, float]] = []
    for item in spans:
        if not predicate(item):
            continue
        start = _epoch_ms(item.get("started_at"))
        end = _epoch_ms(item.get("finished_at"))
        if start is not None and end is not None and end > start:
            intervals.append((start, end))
    return _union_ms(intervals)


def _metadata_total(spans: list[dict[str, Any]], key: str) -> int:
    return sum(
        int((item.get("metadata") or {}).get(key) or 0)
        for item in spans
    )


def _step_category(name: str) -> str:
    value = name.casefold()
    if any(token in value for token in (
        "set up job", "checkout", "setup python", "setup node",
        "restore versioned", "rehydrate previously promoted",
    )):
        return "GITHUB_SETUP_TIME"
    if "prepare canonical runtime and focused delegation gates" in value:
        return "PREFLIGHT_TIME"
    if "materialize existing antigravity" in value:
        return "ANTIGRAVITY_MATERIALIZATION_TIME"
    if "start tuxevil" in value:
        return "PROVIDER_STARTUP_TIME"
    if "publish runner-local codex health" in value:
        return "RUNTIME_HEALTH_PUBLICATION_TIME"
    if "execute first real natural-goal mission" in value or (
        "execute second similar mission" in value
    ):
        return "MISSION_EXECUTION_TIME"
    if "build or validate versioned" in value:
        return "DEPENDENCY_INSTALL_TIME"
    if "upload" in value and any(
        token in value for token in ("artifact", "evidence", "diagnostic")
    ):
        return "ARTIFACT_UPLOAD_TIME"
    if "research" in value:
        return "EXTERNAL_RESEARCH_TIME"
    if "product e2e" in value or "multi-agent" in value or "assert evidence" in value:
        return "CONTROL_PLANE_TIME"
    return "CONTROL_PLANE_TIME"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    args = parser.parse_args()

    events: list[dict[str, Any]] = []
    if args.trace.is_file():
        for raw in args.trace.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                value = json.loads(raw)
                if isinstance(value, dict):
                    events.append(value)

    spans, trace_metrics = _span_metrics(events)
    github = _github_job(str(args.run_id or ""))
    step_intervals: list[tuple[float, float]] = []
    step_exclusive_total = 0.0
    step_category_exclusive: dict[str, float] = defaultdict(float)
    trace_intervals = [
        (_epoch_ms(event.get("started_at")), _epoch_ms(event.get("finished_at")))
        for event in events
    ]
    trace_intervals = [
        (a, b) for a, b in trace_intervals
        if a is not None and b is not None and b > a
    ]

    for step in github.get("steps") or ():
        start = _epoch_ms(step.get("started_at"))
        end = _epoch_ms(step.get("effective_completed_at") or step.get("completed_at"))
        if start is None or end is None or end <= start:
            continue
        interval = (start, end)
        step_intervals.append(interval)
        contained = []
        for child in trace_intervals:
            clipped = _intersection(child, interval)
            if clipped is not None:
                contained.append(clipped)
        exclusive = max(0.0, (end - start) - _union_ms(contained))
        step["exclusive_untraced_ms"] = round(exclusive, 3)
        step["category"] = _step_category(str(step.get("name") or ""))
        step_exclusive_total += exclusive
        step_category_exclusive[step["category"]] += exclusive

    step_active_ms = _union_ms(step_intervals)
    queue_ms = float(github.get("queue_wait_ms") or 0.0)
    wall_clock_ms = float(github.get("wall_clock_ms") or (trace_metrics["trace_active_wall_ms"] + queue_ms))
    critical_path_ms = queue_ms + step_active_ms if github.get("available") else trace_metrics["trace_active_wall_ms"]
    cumulative_work_ms = step_exclusive_total + trace_metrics["trace_cumulative_work_ms"]
    idle_or_unattributed_ms = max(0.0, wall_clock_ms - queue_ms - step_active_ms)
    retry_ms = sum(float(event.get("backoff_ms") or 0.0) for event in events)
    waiting_intervals=[]
    useful_intervals=[]
    redundant_intervals=[]
    human_wait_intervals=[]
    external_wait_intervals=[]
    for event in events:
        start=_epoch_ms(event.get("started_at")); end=_epoch_ms(event.get("finished_at"))
        if start is None or end is None or end <= start:
            continue
        interval=(start,end)
        work_class=str(event.get("work_class") or "NECESSARY").upper()
        category=str(event.get("category") or "")
        if work_class in {"WAITING","BLOCKED"}:
            waiting_intervals.append(interval)
            if "HUMAN" in category or "AUTH" in category:
                human_wait_intervals.append(interval)
            else:
                external_wait_intervals.append(interval)
        elif work_class in {"REDUNDANT","REPEATED","INVALIDATED"}:
            redundant_intervals.append(interval)
        else:
            useful_intervals.append(interval)
    active_work_ms=_union_ms(useful_intervals + redundant_intervals)
    waiting_ms=_union_ms(waiting_intervals)
    useful_work_ms=_union_ms(useful_intervals)
    redundant_work_ms=_union_ms(redundant_intervals)
    waiting_human_ms=_union_ms(human_wait_intervals)
    waiting_external_ms=_union_ms(external_wait_intervals)

    provider_calls = [
        {
            "trace_id": item.get("trace_id"),
            "span_id": item.get("span_id"),
            "parent_span_id": item.get("parent_span_id"),
            "stage": item.get("stage"),
            "inclusive_ms": item.get("inclusive_ms"),
            "exclusive_ms": item.get("exclusive_ms"),
            "provider": item.get("provider"),
            "model": item.get("model"),
            "input_size": item.get("input_size"),
            "output_size": item.get("output_size"),
            "success": item.get("success"),
            "failure_type": item.get("failure_type"),
            **{
                key: (item.get("metadata") or {}).get(key)
                for key in (
                    "cli_process_launch_ms",
                    "cli_process_startup_ms",
                    "model_first_token_ms",
                    "model_total_ms",
                    "json_parse_ms",
                    "process_teardown_ms",
                    "event_count",
                    "tool_call_count",
                    "parse_errors",
                )
            },
        }
        for item in spans if item.get("provider")
    ]

    slowest = sorted(
        spans,
        key=lambda item: float(item.get("inclusive_ms") or 0.0),
        reverse=True,
    )[:20]
    category_cumulative = dict(trace_metrics["category_cumulative_work_ms"])
    for category, value in step_category_exclusive.items():
        category_cumulative[category] = category_cumulative.get(category, 0.0) + value

    mission_roots = [
        item for item in spans
        if item.get("stage") == "delegation-plane.mission"
        and str(item.get("trace_id") or "").strip()
    ]
    mission_trace_id = (
        str(mission_roots[-1].get("trace_id"))
        if mission_roots else ""
    )
    mission_spans = [
        item for item in spans
        if mission_trace_id
        and str(item.get("trace_id") or "") == mission_trace_id
    ]
    mission_codex_launches = sum(
        1
        for item in mission_spans
        if (item.get("metadata") or {}).get("tool") == "codex"
        and item.get("category") == "AI_PROVIDER_TIME"
    )
    mission_git_invocations = sum(
        1
        for item in mission_spans
        if (item.get("metadata") or {}).get("tool") == "git"
    )
    mission_context_bytes = sum(
        int(item.get("input_size") or 0)
        for item in mission_spans
        if item.get("category") == "AI_PROVIDER_TIME"
        and item.get("provider") == "codex"
    )
    mission_repeated_spans = [
        item for item in mission_spans
        if str(item.get("work_class") or "").upper()
        in {"REDUNDANT", "REPEATED", "INVALIDATED"}
    ]
    mission_retry_ms = sum(
        float(item.get("inclusive_ms") or 0.0)
        for item in mission_repeated_spans
        if item.get("category") == "AGENT_ATTEMPT_TIME"
    )

    codex_process_launches = sum(
        1
        for item in spans
        if (item.get("metadata") or {}).get("tool") == "codex"
        and item.get("category") == "AI_PROVIDER_TIME"
    )
    git_invocations = sum(
        1
        for item in spans
        if (item.get("metadata") or {}).get("tool") == "git"
    )
    context_bytes = sum(
        int(item.get("input_size") or 0)
        for item in spans
        if item.get("provider") == "codex"
    )
    cache_hits = sum(1 for item in spans if item.get("cache_hit") is True)
    cache_misses = sum(1 for item in spans if item.get("cache_hit") is False)
    repeated_spans = [
        item for item in spans
        if str(item.get("work_class") or "").upper()
        in {"REDUNDANT", "REPEATED", "INVALIDATED"}
    ]
    retries_before = sum(
        max(0, int(item.get("attempt_count") or 1) - 1)
        for item in spans
        if item.get("category") == "AGENT_EXECUTION_TIME"
    )
    named_step_ms: dict[str, float] = defaultdict(float)
    for step in github.get("steps") or ():
        named_step_ms[str(step.get("category") or "CONTROL_PLANE_TIME")] += float(
            step.get("duration_ms") or 0.0
        )
    planning_ms = sum(
        float(item.get("inclusive_ms") or 0.0)
        for item in spans
        if item.get("category") == "HARNESS_PLANNING_TIME"
    )
    agent_attempts = [
        item for item in spans if item.get("category") == "AGENT_ATTEMPT_TIME"
    ]
    agent_attempt_ms = sum(float(item.get("inclusive_ms") or 0.0) for item in agent_attempts)
    redundant_attempt_ms = sum(
        float(item.get("inclusive_ms") or 0.0)
        for item in agent_attempts
        if str(item.get("work_class") or "").upper() == "REPEATED"
    )

    category_cp = dict(trace_metrics["category_critical_path_ms"])
    pip_install_ms = float(category_cp.get("PREFLIGHT_PIP_INSTALL_TIME", 0.0))
    focused_tests_ms = float(category_cp.get("PREFLIGHT_FOCUSED_TESTS_TIME", 0.0))
    codex_bootstrap_ms = float(category_cp.get("PREFLIGHT_CODEX_BOOTSTRAP_TIME", 0.0))
    hermes_bootstrap_ms = float(category_cp.get("PREFLIGHT_HERMES_BOOTSTRAP_TIME", 0.0))
    other_preflight_ms = float(category_cp.get("PREFLIGHT_OTHER_TIME", 0.0))
    antigravity_materialization_ms = float(named_step_ms.get("ANTIGRAVITY_MATERIALIZATION_TIME", 0.0))
    tuxevil_startup_ms = float(category_cp.get("TUXEVIL_STARTUP_TIME", 0.0))
    tuxevil_live_proof_ms = float(category_cp.get("TUXEVIL_LIVE_PROOF_TIME", 0.0))
    runtime_health_publication_ms = float(named_step_ms.get("RUNTIME_HEALTH_PUBLICATION_TIME", 0.0))
    natural_goal_parse_ms = float(category_cp.get("PLANNING_NATURAL_GOAL_PARSE_TIME", 0.0))
    semantic_planner_ms = float(category_cp.get("PLANNING_SEMANTIC_PLANNER_TIME", 0.0))
    registry_retrieval_ms = float(category_cp.get("PLANNING_REGISTRY_RETRIEVAL_TIME", 0.0))
    competence_lookup_ms = float(category_cp.get("PLANNING_COMPETENCE_LOOKUP_TIME", 0.0))
    failure_memory_lookup_ms = float(category_cp.get("PLANNING_FAILURE_MEMORY_LOOKUP_TIME", 0.0))
    health_lookup_ms = float(category_cp.get("PLANNING_HEALTH_LOOKUP_TIME", 0.0))
    mission_plan_normalization_ms = float(category_cp.get("PLANNING_MISSION_PLAN_NORMALIZATION_TIME", 0.0))
    task_envelope_build_ms = float(category_cp.get("PLANNING_TASK_ENVELOPE_BUILD_TIME", 0.0))
    planner_model_calls = _metadata_total(spans, "planner_model_calls")
    registry_read_count = _metadata_total(spans, "registry_read_count")
    health_read_count = _metadata_total(spans, "health_read_count")
    competence_read_count = _metadata_total(spans, "competence_read_count")
    failure_memory_read_count = _metadata_total(spans, "failure_memory_read_count")
    context_fingerprints = [
        str((item.get("metadata") or {}).get("context_fingerprint"))
        for item in spans
        if (item.get("metadata") or {}).get("context_fingerprint")
    ]
    duplicate_context_build_count = max(0, len(context_fingerprints) - len(set(context_fingerprints)))
    planning_context_bytes = max(
        [int((item.get("metadata") or {}).get("planning_context_bytes") or 0) for item in spans] + [0]
    )
    mission_execution_ms = max(
        [float(item.get("inclusive_ms") or 0.0) for item in mission_roots] + [0.0]
    )
    readonly_analysis_ms = _filtered_union_ms(
        mission_spans,
        lambda item: "readonly-analysis" in str(item.get("capability_id") or ""),
    )
    candidate_ms = _filtered_union_ms(
        mission_spans,
        lambda item: item.get("category") == "AGENT_ATTEMPT_TIME"
        and str(item.get("capability_id") or "") == "agent-office.codex.bounded-development",
    )
    initial_pass_ms = float(category_cp.get("CODEX_INITIAL_PASS_TIME", 0.0))
    candidate_repair_ms = float(category_cp.get("CODEX_CANDIDATE_REPAIR_TIME", 0.0))
    final_validation_ms = float(category_cp.get("CODEX_FINAL_VALIDATION_TIME", 0.0))
    kanban_op_count = _metadata_total(mission_spans, "kanban_op_count")
    handoff_count = _metadata_total(mission_spans, "handoff_count")
    context_package_count = _metadata_total(mission_spans, "context_package_count")
    hermes_context_bytes = _metadata_total(mission_spans, "context_bytes")
    wait_for_dependency_ms = float(category_cp.get("HERMES_DEPENDENCY_WAIT_TIME", 0.0))
    specialist_spans = [
        item for item in mission_spans
        if item.get("category") == "HERMES_SPECIALIST_EXECUTION_TIME"
    ]
    specialist_wall_ms = _filtered_union_ms(specialist_spans, lambda _item: True)
    specialist_cumulative_ms = sum(float(item.get("inclusive_ms") or 0.0) for item in specialist_spans)
    parallel_execution_ms = max(0.0, specialist_cumulative_ms - specialist_wall_ms)
    serial_execution_ms = specialist_wall_ms
    mission_python_launches = sum(1 for item in mission_spans if (item.get("metadata") or {}).get("tool") == "python")
    mission_pytest_launches = sum(1 for item in mission_spans if (item.get("metadata") or {}).get("tool") == "pytest")
    mission_shell_launches = sum(1 for item in mission_spans if (item.get("metadata") or {}).get("tool") in {"bash", "sh"})
    provider_startup_total_ms = (
        antigravity_materialization_ms
        + float(named_step_ms.get("PROVIDER_STARTUP_TIME", 0.0))
        + runtime_health_publication_ms
    )

    report = {
        "schema_version": 2,
        "status": "PASS",
        "run_id": args.run_id or None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "event_count": len(events),
        "WALL_CLOCK_MS": round(wall_clock_ms, 3),
        "E2E_WALL_CLOCK_MS": round(wall_clock_ms, 3),
        "ACTIVE_WORK_MS": round(active_work_ms, 3),
        "WAITING_MS": round(waiting_ms, 3),
        "CUMULATIVE_WORK_MS": round(cumulative_work_ms, 3),
        "CRITICAL_PATH_MS": round(critical_path_ms, 3),
        "EXCLUSIVE_MS": round(cumulative_work_ms, 3),
        "INCLUSIVE_MS": round(sum(float(item.get("inclusive_ms") or 0.0) for item in spans), 3),
        "PARALLELISM_SAVED_MS": round(float(trace_metrics["parallelism_saved_ms"]), 3),
        "IDLE_OR_UNATTRIBUTED_MS": round(idle_or_unattributed_ms, 3),
        "IDLE_OR_UNKNOWN_MS": round(idle_or_unattributed_ms, 3),
        "USEFUL_WORK_MS": round(useful_work_ms, 3),
        "WAITING_EXTERNAL_MS": round(waiting_external_ms, 3),
        "WAITING_HUMAN_MS": round(waiting_human_ms, 3),
        "CI_OVERHEAD_MS": round(sum(v for k,v in step_category_exclusive.items() if k in {"GITHUB_SETUP_TIME","DEPENDENCY_INSTALL_TIME"}), 3),
        "CI_USEFUL_WORK_MS": round(max(0.0, cumulative_work_ms - sum(v for k,v in step_category_exclusive.items() if k in {"GITHUB_SETUP_TIME","DEPENDENCY_INSTALL_TIME"})), 3),
        "REDUNDANT_WORK_MS": round(redundant_work_ms, 3),
        "AVOIDABLE_RETRY_MS": round(retry_ms, 3),
        "PROVIDER_CRITICAL_PATH_MS": round(float(trace_metrics["provider_critical_path_ms"]), 3),
        "PROVIDER_CUMULATIVE_WORK_MS": round(float(trace_metrics["provider_cumulative_work_ms"]), 3),
        "GITHUB_QUEUE_TIME_MS": round(queue_ms, 3),
        "GITHUB_RUNNER_TIME_MS": round(float(github.get("runner_elapsed_ms") or 0.0), 3),
        "TRACE_ACTIVE_WALL_MS": round(float(trace_metrics["trace_active_wall_ms"]), 3),
        "RETRY_TIME_MS": round(retry_ms, 3),
        "BOOTSTRAP_MS": round(float(named_step_ms.get("GITHUB_SETUP_TIME", 0.0)), 3),
        "PREFLIGHT_MS": round(float(named_step_ms.get("PREFLIGHT_TIME", 0.0)), 3),
        "PROVIDER_STARTUP_MS": round(provider_startup_total_ms, 3),
        "PLANNING_MS": round(planning_ms, 3),
        "MISSION_EXECUTION_MS": round(mission_execution_ms, 3),
        "HERMES_MS": round(float(category_cp.get("HERMES_RUNTIME_TIME", 0.0)), 3),
        "AGENT_ATTEMPT_MS": round(agent_attempt_ms, 3),
        "READONLY_ANALYSIS_MS": round(readonly_analysis_ms, 3),
        "CANDIDATE_MS": round(candidate_ms, 3),
        "INITIAL_PASS_MS": round(initial_pass_ms, 3),
        "CANDIDATE_REPAIR_MS": round(candidate_repair_ms, 3),
        "FINAL_VALIDATION_MS": round(final_validation_ms, 3),
        "PIP_INSTALL_MS": round(pip_install_ms, 3),
        "FOCUSED_TESTS_MS": round(focused_tests_ms, 3),
        "CODEX_BOOTSTRAP_MS": round(codex_bootstrap_ms, 3),
        "HERMES_BOOTSTRAP_MS": round(hermes_bootstrap_ms, 3),
        "OTHER_PREFLIGHT_MS": round(other_preflight_ms, 3),
        "ANTIGRAVITY_MATERIALIZATION_MS": round(antigravity_materialization_ms, 3),
        "TUXEVIL_STARTUP_MS": round(tuxevil_startup_ms, 3),
        "TUXEVIL_LIVE_PROOF_MS": round(tuxevil_live_proof_ms, 3),
        "RUNTIME_HEALTH_PUBLICATION_MS": round(runtime_health_publication_ms, 3),
        "NATURAL_GOAL_PARSE_MS": round(natural_goal_parse_ms, 3),
        "SEMANTIC_PLANNER_MS": round(semantic_planner_ms, 3),
        "REGISTRY_RETRIEVAL_MS": round(registry_retrieval_ms, 3),
        "COMPETENCE_LOOKUP_MS": round(competence_lookup_ms, 3),
        "FAILURE_MEMORY_LOOKUP_MS": round(failure_memory_lookup_ms, 3),
        "HEALTH_LOOKUP_MS": round(health_lookup_ms, 3),
        "MISSION_PLAN_NORMALIZATION_MS": round(mission_plan_normalization_ms, 3),
        "TASK_ENVELOPE_BUILD_MS": round(task_envelope_build_ms, 3),
        "PLANNER_MODEL_CALLS": planner_model_calls,
        "PLANNING_CONTEXT_BYTES": planning_context_bytes,
        "REGISTRY_READ_COUNT": registry_read_count,
        "HEALTH_READ_COUNT": health_read_count,
        "COMPETENCE_READ_COUNT": competence_read_count,
        "FAILURE_MEMORY_READ_COUNT": failure_memory_read_count,
        "DUPLICATE_CONTEXT_BUILD_COUNT": duplicate_context_build_count,
        "KANBAN_OP_COUNT": kanban_op_count,
        "HANDOFF_COUNT": handoff_count,
        "CONTEXT_PACKAGE_COUNT": context_package_count,
        "HERMES_CONTEXT_BYTES": hermes_context_bytes,
        "WAIT_FOR_DEPENDENCY_MS": round(wait_for_dependency_ms, 3),
        "PARALLEL_EXECUTION_MS": round(parallel_execution_ms, 3),
        "SERIAL_EXECUTION_MS": round(serial_execution_ms, 3),
        "RETRY_MS": round(redundant_attempt_ms, 3),
        "ARTIFACT_MS": round(float(named_step_ms.get("ARTIFACT_UPLOAD_TIME", 0.0)), 3),
        "TOTAL_WALL_CLOCK_MS": round(wall_clock_ms, 3),
        "CODEX_PROCESS_LAUNCHES": codex_process_launches,
        "GIT_INVOCATIONS": git_invocations,
        "CONTEXT_BYTES": context_bytes,
        "CACHE_HITS": cache_hits,
        "CACHE_MISSES": cache_misses,
        "REUSED_EVIDENCE_COUNT": sum(
            1 for item in spans
            if bool((item.get("metadata") or {}).get("reused_evidence"))
        ),
        "AVOIDED_DUPLICATE_WORK_COUNT": sum(
            int((item.get("metadata") or {}).get("avoided_duplicate_work") or 0)
            for item in spans
        ),
        "REPEATED_SPAN_COUNT": len(repeated_spans),
        "RETRIES_OBSERVED": retries_before,
        "MISSION_TRACE_ID": mission_trace_id or None,
        "MISSION_CODEX_PROCESS_LAUNCHES": mission_codex_launches,
        "MISSION_GIT_INVOCATIONS": mission_git_invocations,
        "MISSION_PYTHON_PROCESS_LAUNCHES": mission_python_launches,
        "MISSION_PYTEST_PROCESS_LAUNCHES": mission_pytest_launches,
        "MISSION_SHELL_PROCESS_LAUNCHES": mission_shell_launches,
        "MISSION_CONTEXT_BYTES": mission_context_bytes,
        "MISSION_REPEATED_SPAN_COUNT": len(mission_repeated_spans),
        "MISSION_RETRY_MS": round(mission_retry_ms, 3),
        "category_critical_path_ms": trace_metrics["category_critical_path_ms"],
        "category_cumulative_work_ms": dict(sorted(category_cumulative.items())),
        "spans": spans,
        "slowest_stages": slowest,
        "provider_calls": provider_calls,
        "github_actions": github,
        "waste_candidates": [
            {
                "stage": item.get("stage"),
                "duration_ms": item.get("inclusive_ms"),
                "work_class": item.get("work_class"),
                "category": item.get("category"),
            }
            for item in spans
            if str(item.get("work_class") or "").upper() in {"REDUNDANT","REPEATED","INVALIDATED"}
        ],
        "methodology": {
            "wall_clock": "GitHub job created_at to completed_at/current time",
            "critical_path": "runner queue plus union of observed GitHub step intervals",
            "cumulative_work": "sum of exclusive trace-span work plus untraced exclusive GitHub-step work",
            "parallelism_saved": "trace cumulative exclusive work minus union of trace intervals",
            "provider_critical_path": "union of provider span intervals; concurrent provider calls counted once on wall clock",
            "nested_spans": "parent_span_id removes direct-child interval union from parent exclusive time",
            "registry_read_count": "logical canonical Registry get/discover operations instrumented in planning",
            "health_read_count": "logical capability/provider health lookups instrumented in planning",
            "parallel_execution_ms": "specialist cumulative execution minus union wall time; measures overlap saved",
            "serial_execution_ms": "union wall time of specialist execution spans",
            "kanban_op_count": "observed Hermes event plus comment operations in the final board snapshot",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for key in (
        "E2E_WALL_CLOCK_MS",
        "ACTIVE_WORK_MS",
        "WAITING_MS",
        "CUMULATIVE_WORK_MS",
        "CRITICAL_PATH_MS",
        "PARALLELISM_SAVED_MS",
        "IDLE_OR_UNATTRIBUTED_MS",
        "PROVIDER_CRITICAL_PATH_MS",
        "PROVIDER_CUMULATIVE_WORK_MS",
        "GITHUB_QUEUE_TIME_MS",
        "RETRY_TIME_MS",
        "PIP_INSTALL_MS",
        "FOCUSED_TESTS_MS",
        "CODEX_BOOTSTRAP_MS",
        "HERMES_BOOTSTRAP_MS",
        "OTHER_PREFLIGHT_MS",
        "ANTIGRAVITY_MATERIALIZATION_MS",
        "TUXEVIL_STARTUP_MS",
        "TUXEVIL_LIVE_PROOF_MS",
        "RUNTIME_HEALTH_PUBLICATION_MS",
        "NATURAL_GOAL_PARSE_MS",
        "SEMANTIC_PLANNER_MS",
        "REGISTRY_RETRIEVAL_MS",
        "COMPETENCE_LOOKUP_MS",
        "FAILURE_MEMORY_LOOKUP_MS",
        "HEALTH_LOOKUP_MS",
        "MISSION_PLAN_NORMALIZATION_MS",
        "TASK_ENVELOPE_BUILD_MS",
    ):
        print(f"{key}={float(report[key]):.3f}")
    if slowest:
        print(f"SLOWEST_STAGE={slowest[0].get('stage')}")
        print(f"SLOWEST_STAGE_INCLUSIVE_MS={float(slowest[0].get('inclusive_ms') or 0.0):.3f}")
        print(f"SLOWEST_STAGE_EXCLUSIVE_MS={float(slowest[0].get('exclusive_ms') or 0.0):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
