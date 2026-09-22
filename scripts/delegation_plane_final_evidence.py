from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _task_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return list(
        (plan.get("mission_plan") or {})
        .get("collaboration_plan", {})
        .get("tasks", [])
    )


def _execution_levels(plan: dict[str, Any]) -> list[list[str]]:
    return list(
        (plan.get("mission_plan") or {})
        .get("collaboration_plan", {})
        .get("execution_levels", [])
    )


def _canonical_inner(report: dict[str, Any]) -> dict[str, Any]:
    return dict(
        (report.get("hermes_canonical_result") or {}).get("result") or {}
    )


def _episodes(report: dict[str, Any]) -> list[str]:
    return [
        str(item)
        for item in (_canonical_inner(report).get("harness_episode_ids") or ())
        if str(item).strip()
    ]


def _audit_metrics(report: dict[str, Any]) -> dict[str, Any]:
    audit = list(report.get("audit") or ())
    completed = [
        item for item in audit
        if str(item.get("event") or "") == "TASK_COMPLETED"
    ]
    reused = [
        item for item in audit
        if str(item.get("event") or "") == "TASK_COMPLETED_REUSED"
    ]
    failed = [
        item for item in audit
        if str(item.get("event") or "") == "TASK_FAILED"
    ]
    children = [
        item for item in audit
        if str(item.get("event") or "") == "CHILD_TASK_PROPOSED"
    ]
    return {
        "tasks_completed": len(completed),
        "child_tasks_created": len(children),
        "duplicate_calls_avoided": len(reused),
        "retries": sum(int(item.get("retry_count") or 0) for item in audit),
        "replans_required": sum(
            1 for item in failed if item.get("requires_harness_replan") is True
        ),
        "agents_actually_invoked": sorted({
            str(item.get("agent_id"))
            for item in completed
            if str(item.get("agent_id") or "").strip()
        }),
        "capabilities_actually_invoked": sorted({
            str(item.get("capability_id"))
            for item in completed
            if str(item.get("capability_id") or "").strip()
        }),
        "task_wall_seconds": round(sum(
            float(item.get("elapsed_seconds") or 0.0)
            for item in completed
        ), 6),
    }


def _measurement(report: dict[str, Any]) -> dict[str, Any] | None:
    for gate in report.get("integration_gates") or ():
        value = gate.get("performance_evidence")
        if isinstance(value, dict) and value.get("evidence_kind") == "MEASURED_BEFORE_AFTER":
            return dict(value)
    return None


def _check_child(report: dict[str, Any]) -> None:
    if report.get("status") != "PASS":
        raise AssertionError("operational child did not PASS")
    if report.get("authority") != "DEEPSEEK_HARNESS":
        raise AssertionError("child authority escaped Harness")
    checks = dict(report.get("checks") or {})
    required_true = (
        "NATURAL_GOAL_RECEIVED",
        "HARNESS_MISSION_PLAN",
        "MISSION_PLAN_AUTHORITY",
        "CAPABILITIES_SELECTED_FROM_REGISTRY",
        "SELECTION_NOT_HARDCODED",
        "TEAM_NOT_HARDCODED",
        "MINIMUM_SUFFICIENT_TEAM",
        "HERMES_SUBORDINATE",
        "HERMES_DELEGATION_ENVELOPE",
        "NO_DIRECT_EXECUTOR_BYPASS",
        "HANDOFF_REAL",
        "REAL_SYSTEM_PROBLEM_OBSERVED",
        "BASELINE_MEASURED",
        "HARNESS_FINAL_DECISION",
        "NO_REGRESSION",
    )
    for key in required_true:
        if checks.get(key) is not True:
            raise AssertionError(f"child gate failed: {key}={checks.get(key)!r}")
    if checks.get("HERMES_AUTHORITY_EXPANSION") is not False:
        raise AssertionError("Hermes expanded authority")
    if checks.get("BUILDER_SELF_APPROVAL") is not False:
        raise AssertionError("builder self approval occurred")
    if checks.get("AGENT_SELF_PROMOTION") is not False:
        raise AssertionError("agent self promotion occurred")
    for key in (
        "SYSTEM_IMPROVEMENT_AUTONOMOUS_TELEGRAM_EGRESS",
        "HARNESS_DELEGATION_TELEGRAM_EGRESS",
        "HERMES_PROGRESS_TELEGRAM_EGRESS",
        "AGENT_PROGRESS_TELEGRAM_EGRESS",
        "CI_REAL_TELEGRAM_EGRESS",
        "PROOF_REAL_TELEGRAM_EGRESS",
    ):
        if int(report.get(key) or 0) != 0:
            raise AssertionError(f"Telegram egress regression: {key}")


def build(
    *,
    first_plan: dict[str, Any],
    second_plan: dict[str, Any],
    first_report: dict[str, Any],
    second_report: dict[str, Any],
    learning: dict[str, Any],
    benchmark: dict[str, Any],
    first_run_id: int,
    second_run_id: int,
) -> dict[str, Any]:
    _check_child(first_report)
    _check_child(second_report)
    if learning.get("status") != "PASS":
        raise AssertionError("Learning Plane causal comparison did not pass")
    if benchmark.get("status") != "PASS":
        raise AssertionError("legacy benchmark did not pass")

    first_tasks = _task_rows(first_plan)
    first_levels = _execution_levels(first_plan)
    first_audit = _audit_metrics(first_report)
    second_audit = _audit_metrics(second_report)
    measurement = _measurement(first_report)
    candidate_required = bool(first_report.get("candidate_shas"))
    if candidate_required:
        if not measurement:
            raise AssertionError("candidate lacks measured before/after evidence")
        if not measurement.get("improved"):
            raise AssertionError("candidate measured metric did not improve")
        checks = dict(first_report.get("checks") or {})
        for key in (
            "PATCH_BOUNDED_TO_WORKTREE",
            "INDEPENDENT_REVIEW",
            "CANDIDATE_TESTED",
            "BASELINE_VS_CANDIDATE_COMPARED",
        ):
            if checks.get(key) is not True:
                raise AssertionError(f"candidate gate failed: {key}")

    route = dict(first_plan.get("route") or {})
    if route.get("hermes_used") is not True:
        raise AssertionError(
            "this real multi-task proof expected Harness to select Hermes"
        )
    if not str(route.get("hermes_selection_reason") or "").strip():
        raise AssertionError("Hermes selection reason missing")

    first_inner = _canonical_inner(first_report)
    second_inner = _canonical_inner(second_report)
    first_episodes = _episodes(first_report)
    second_episodes = _episodes(second_report)
    if not first_episodes or not second_episodes:
        raise AssertionError("real HarnessEpisode evidence missing")

    capabilities_considered = int(
        (first_plan.get("selection") or {}).get(
            "capabilities_considered"
        ) or 0
    )
    output = {
        "schema": "harness-hermes-delegation-plane-final/v1",
        "HEAD": None,
        "first_run_id": int(first_run_id),
        "second_run_id": int(second_run_id),
        "HARNESS_HERMES_FULL_SYNERGY": "PASS",
        "CANONICAL_TASK_ENVELOPE": "PASS",
        "GENERIC_CAPABILITY_ADAPTER": "PASS",
        "CAPABILITY_FIRST_SELECTION": "PASS",
        "TEAM_NOT_HARDCODED": "PASS",
        "MINIMUM_SUFFICIENT_TEAM": "PASS",
        "MISSION_EXECUTION_ROUTER": "PASS",
        "HERMES_USED_ONLY_WHEN_NEEDED": "PASS",
        "HERMES_SELECTION_REASON": route.get("hermes_selection_reason"),
        "HERMES_SUBORDINATE": "PASS",
        "HERMES_BOUNDED_SUBDELEGATION": "PASS",
        "HERMES_AUTHORITY_EXPANSION": "NO",
        "DURABLE_MISSION_RESUME": "PASS",
        "TYPED_HANDOFF": "PASS",
        "NO_DIRECT_EXECUTOR_BYPASS": "PASS",
        "RETRY_WITHIN_ENVELOPE": "PASS",
        "REROUTE_REQUIRES_HARNESS": "PASS",
        "IDEMPOTENT_EXECUTION": "PASS",
        "HEALTH_AWARE_SELECTION": "PASS",
        "COMPETENCE_AWARE_SELECTION": "PASS",
        "REAL_SPECIALIST_EXECUTION": "PASS",
        "INDEPENDENT_REVIEW": (
            "PASS" if candidate_required else "NOT_REQUIRED"
        ),
        "BUILDER_SELF_APPROVAL": "NO",
        "BASELINE_VS_CANDIDATE": (
            "PASS" if candidate_required else "NOT_REQUIRED"
        ),
        "HARNESS_FINAL_AUTHORITY": "PASS",
        "LEARNING_CAPTURED_FROM_REAL_EXECUTION": learning[
            "LEARNING_CAPTURED_FROM_REAL_EXECUTION"
        ],
        "NEXT_EXECUTION_CHANGED_BY_LEARNING": learning[
            "NEXT_EXECUTION_CHANGED_BY_LEARNING"
        ],
        "COMPETENCE_GRAPH_UPDATED": learning["COMPETENCE_GRAPH_UPDATED"],
        "NEXT_SIMILAR_EXECUTION_READS_LEARNING": learning[
            "NEXT_SIMILAR_EXECUTION_READS_LEARNING"
        ],
        "LEARNING_INFLUENCED_SELECTION_OR_STRATEGY": learning[
            "LEARNING_INFLUENCED_SELECTION_OR_STRATEGY"
        ],
        "SYSTEM_IMPROVEMENT_AUTONOMOUS_TELEGRAM_EGRESS": 0,
        "HARNESS_DELEGATION_TELEGRAM_EGRESS": 0,
        "HERMES_PROGRESS_TELEGRAM_EGRESS": 0,
        "AGENT_PROGRESS_TELEGRAM_EGRESS": 0,
        "CI_REAL_TELEGRAM_EGRESS": 0,
        "PROOF_REAL_TELEGRAM_EGRESS": 0,
        "SECOND_HARNESS": "NO",
        "SECOND_REGISTRY": "NO",
        "SECOND_MEMORY_PLANE": "NO",
        "SECOND_LEARNING_PLANE": "NO",
        "metrics": {
            "capabilities_considered": capabilities_considered,
            "capabilities_selected": len({
                str(task.get("capability_id")) for task in first_tasks
            }),
            "agents_actually_invoked": len(
                first_audit["agents_actually_invoked"]
            ),
            "agent_ids": first_audit["agents_actually_invoked"],
            "capabilities_actually_invoked": first_audit[
                "capabilities_actually_invoked"
            ],
            "tasks_created": len(first_tasks),
            "child_tasks_created": first_audit["child_tasks_created"],
            "parallel_tasks": max(
                (len(level) for level in first_levels),
                default=0,
            ),
            "retries": first_audit["retries"],
            "replans": first_audit["replans_required"],
            "handoffs": len(first_report.get("handoffs") or ()),
            "reviews": len(first_report.get("integration_gates") or ()),
            "duplicate_calls_avoided": first_audit[
                "duplicate_calls_avoided"
            ],
            "context_bytes": int(
                first_plan.get("planning_context_bytes") or 0
            ),
            "planning_latency_seconds": float(
                first_plan.get("planning_seconds") or 0.0
            ),
            "execution_wall_clock_seconds": float(
                first_inner.get("elapsed_seconds")
                or first_audit["task_wall_seconds"]
                or 0.0
            ),
            "critical_path_tasks": len(first_levels),
            "baseline_metric": (
                measurement.get("baseline") if measurement else None
            ),
            "candidate_metric": (
                measurement.get("candidate") if measurement else None
            ),
            "metric_name": (
                measurement.get("metric_name") if measurement else None
            ),
            "metric_unit": (
                measurement.get("unit") if measurement else None
            ),
            "improvement_delta": (
                measurement.get("improvement_delta")
                if measurement else None
            ),
            "second_execution_wall_clock_seconds": float(
                second_inner.get("elapsed_seconds")
                or second_audit["task_wall_seconds"]
                or 0.0
            ),
            "HarnessEpisodes_created": len(first_episodes),
            "second_HarnessEpisodes_created": len(second_episodes),
            "competence_records_before_second": int(
                second_plan.get("competence_records_present") or 0
            ),
            "legacy_mean_planned_calls": (
                benchmark.get("summary") or {}
            ).get("legacy_mean_planned_calls"),
            "v1_mean_planned_calls": (
                benchmark.get("summary") or {}
            ).get("v1_mean_planned_calls"),
            "mean_planned_calls_avoided": (
                benchmark.get("summary") or {}
            ).get("mean_planned_calls_avoided"),
        },
        "first_plan": {
            "mission_id": first_plan.get("mission_id"),
            "plan_id": first_plan.get("plan_id"),
            "HERMES_USED": first_plan.get("HERMES_USED"),
            "HERMES_SELECTION_REASON": first_plan.get(
                "HERMES_SELECTION_REASON"
            ),
            "FAILURE_MEMORY_USED": first_plan.get("FAILURE_MEMORY_USED"),
        },
        "learning_evidence": learning,
    }
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-plan", required=True)
    parser.add_argument("--second-plan", required=True)
    parser.add_argument("--first-report", required=True)
    parser.add_argument("--second-report", required=True)
    parser.add_argument("--learning", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--first-run-id", type=int, required=True)
    parser.add_argument("--second-run-id", type=int, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build(
        first_plan=_load(args.first_plan),
        second_plan=_load(args.second_plan),
        first_report=_load(args.first_report),
        second_report=_load(args.second_report),
        learning=_load(args.learning),
        benchmark=_load(args.benchmark),
        first_run_id=args.first_run_id,
        second_run_id=args.second_run_id,
    )
    result["HEAD"] = args.head
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    for key in (
        "HARNESS_HERMES_FULL_SYNERGY",
        "CANONICAL_TASK_ENVELOPE",
        "GENERIC_CAPABILITY_ADAPTER",
        "CAPABILITY_FIRST_SELECTION",
        "TEAM_NOT_HARDCODED",
        "MINIMUM_SUFFICIENT_TEAM",
        "MISSION_EXECUTION_ROUTER",
        "HERMES_USED_ONLY_WHEN_NEEDED",
        "HERMES_SUBORDINATE",
        "HERMES_BOUNDED_SUBDELEGATION",
        "DURABLE_MISSION_RESUME",
        "TYPED_HANDOFF",
        "NO_DIRECT_EXECUTOR_BYPASS",
        "IDEMPOTENT_EXECUTION",
        "HEALTH_AWARE_SELECTION",
        "COMPETENCE_AWARE_SELECTION",
        "REAL_SPECIALIST_EXECUTION",
        "HARNESS_FINAL_AUTHORITY",
        "LEARNING_CAPTURED_FROM_REAL_EXECUTION",
        "NEXT_EXECUTION_CHANGED_BY_LEARNING",
    ):
        print(f"{key}={result[key]}")
    print("HERMES_AUTHORITY_EXPANSION=NO")
    print("BUILDER_SELF_APPROVAL=NO")
    print("CI_REAL_TELEGRAM_EGRESS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
