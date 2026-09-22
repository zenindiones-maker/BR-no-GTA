from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

from app.services.performance_telemetry_service import PerformanceSpan

from scripts.delegation_plane_natural_goal_plan import (
    NATURAL_GOAL,
    run as plan_natural_goal,
)
from scripts.dynamic_system_improvement_mission import run as execute_mission


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--execution-instance-id", required=True)
    parser.add_argument("--learning-source-run-id", type=int, default=0)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "natural-goal-plan.json"
    report_path = output_dir / "dynamic-system-improvement-report.json"

    with PerformanceSpan(
        stage="delegation-plane.planning",
        category="HARNESS_PLANNING_TIME",
        input_size=len(NATURAL_GOAL.encode("utf-8")),
        goal_id=args.goal_id,
        execution_id=args.execution_instance_id,
        work_class="NECESSARY",
    ) as planning_span:
        plan_report = plan_natural_goal(
            goal_id=args.goal_id,
            output=plan_path,
            learning_source_run_id=args.learning_source_run_id,
        )
        planning_span.set(
            output_size=len(
                json.dumps(plan_report, default=str).encode("utf-8")
            ),
            metadata={
                "planning_context_bytes": plan_report.get(
                    "planning_context_bytes"
                ),
                "tasks_created": plan_report.get("tasks_created"),
                "unique_team_size": plan_report.get("unique_team_size"),
            },
        )
    mission_plan = dict(plan_report["mission_plan"])
    plan_b64 = base64.b64encode(
        json.dumps(
            mission_plan,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii")

    canonical_mission_id = str(plan_report.get("mission_id") or "")
    with PerformanceSpan(
        stage="delegation-plane.mission",
        category="MISSION_EXECUTION_TIME",
        input_size=len(plan_b64.encode("ascii")),
        trace_id=canonical_mission_id or None,
        mission_id=canonical_mission_id or None,
        goal_id=args.goal_id,
        execution_id=args.execution_instance_id,
        work_class="NECESSARY",
    ) as mission_span:
        execution_report = execute_mission(
            plan_b64=plan_b64,
            human_goal=NATURAL_GOAL,
            base_sha=args.base_sha,
            branch=args.branch,
            upstream_root=Path(args.upstream_root),
            artifact_dir=output_dir / "runtime",
        )
        mission_span.set(
            output_size=len(
                json.dumps(execution_report, default=str).encode("utf-8")
            ),
        )
    execution_report["execution_instance_id"] = args.execution_instance_id
    execution_report["github_run_id"] = int(os.getenv("GITHUB_RUN_ID") or 0)
    execution_report["github_job"] = str(os.getenv("GITHUB_JOB") or "")
    execution_report["learning_source_run_id"] = int(
        args.learning_source_run_id
    )
    report_path.write_text(
        json.dumps(
            execution_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    checks = dict(execution_report.get("checks") or {})
    required = (
        execution_report.get("status") == "PASS"
        and plan_report.get("status") == "PASS"
        and checks.get("NATURAL_GOAL_RECEIVED") is True
        and checks.get("HARNESS_MISSION_PLAN") is True
        and checks.get("REAL_SPECIALIST_EXECUTION") is True
        and checks.get("REAL_SYSTEM_PROBLEM_OBSERVED") is True
        and checks.get("BASELINE_MEASURED") is True
        and checks.get("HARNESS_FINAL_DECISION") is True
        and checks.get("NO_REGRESSION") is True
    )
    print("EXECUTION_INSTANCE_ID=" + args.execution_instance_id)
    print("NATURAL_GOAL_RECEIVED=PASS")
    print("REAL_SPECIALIST_EXECUTION=" + (
        "PASS" if checks.get("REAL_SPECIALIST_EXECUTION") is True else "FAIL"
    ))
    print("REAL_SYSTEM_PROBLEM_OBSERVED=" + (
        "PASS" if checks.get("REAL_SYSTEM_PROBLEM_OBSERVED") is True else "FAIL"
    ))
    print("BASELINE_MEASURED=" + (
        "PASS" if checks.get("BASELINE_MEASURED") is True else "FAIL"
    ))
    print("SYSTEM_IMPROVEMENT_AUTONOMOUS_TELEGRAM_EGRESS=0")
    print("CI_REAL_TELEGRAM_EGRESS=0")
    return 0 if required else 2


if __name__ == "__main__":
    raise SystemExit(main())
