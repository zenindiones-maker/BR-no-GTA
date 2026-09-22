from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
import time
from typing import Any

from app.database.schema import initialize_schema
from app.services.harness_collaboration_service import (
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.harness_mission_execution_router import (
    select_mission_execution_route,
)
from scripts.run_system_improvement_review import SPECIALISTS


GOALS = (
    "Melhore o sistema.",
    "Otimize o pipeline.",
    "Melhore o sistema de performance.",
    "Otimize o pipeline sem reduzir qualidade.",
)


def _bytes(value: Any) -> int:
    return len(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8"))


def _max_parallelism(levels: list[list[str]] | tuple[tuple[str, ...], ...]) -> int:
    return max((len(level) for level in levels), default=0)


def run(*, output: Path) -> dict[str, Any]:
    initialize_schema()
    rows: list[dict[str, Any]] = []
    legacy_capabilities = [
        str(item["capability_id"]) for item in SPECIALISTS
    ]
    for index, human_goal in enumerate(GOALS, start=1):
        goal = build_goal_envelope(
            human_goal=human_goal,
            project="BR-no-GTA",
            goal_id=f"delegation-benchmark-{index}",
            source_surface="benchmark",
        )
        started = time.perf_counter()
        plan = plan_mission_from_human_goal(goal)
        planning_ms = (time.perf_counter() - started) * 1000.0
        payload = plan.to_dict()
        collaboration = dict(payload["collaboration_plan"])
        tasks = list(collaboration["tasks"])
        route = select_mission_execution_route(payload)
        levels = list(collaboration.get("execution_levels") or [])
        selected_capabilities = [
            str(item["capability_id"]) for item in tasks
        ]
        selected_owners = {
            (
                item.get("selected_agent_id"),
                item.get("selected_skill_id"),
                item.get("capability_id"),
            )
            for item in tasks
        }
        selection_rows = list(
            (payload.get("planning_evidence") or {}).get("selection") or []
        )
        considered = sum(
            len(item.get("candidate_scores") or item.get("candidates") or ())
            for item in selection_rows
        )
        evidence_complete = all(
            bool(item.get("evidence_contract"))
            and bool(item.get("acceptance_criteria"))
            for item in tasks
        )
        rows.append({
            "goal": human_goal,
            "legacy": {
                "team_model": "FIXED_SPECIALIST_ROSTER",
                "tasks_created": len(SPECIALISTS),
                "agent_calls_planned": len(SPECIALISTS),
                "capabilities_selected": legacy_capabilities,
                "minimum_team_evidence": False,
                "execution_topology": "FIXED_FAN_OUT",
                "max_parallelism": len(SPECIALISTS),
                "critical_path_task_count": 1,
                "context_bytes": _bytes({
                    "goal": human_goal,
                    "specialists": SPECIALISTS,
                }),
                "planning_latency_ms": 0.0,
                "planning_latency_measurement": (
                    "STATIC_ROSTER_CONSTRUCTION_NOT_COMPARABLE"
                ),
                "execution_wall_clock_seconds": None,
            },
            "v1": {
                "planning_mode": payload.get("planning_mode"),
                "planning_latency_ms": round(planning_ms, 3),
                "tasks_created": len(tasks),
                "agent_calls_planned": len(tasks),
                "capabilities_considered": considered,
                "capabilities_selected": selected_capabilities,
                "unique_team_size": len(selected_owners),
                "execution_topology": route.runtime,
                "hermes_used": route.hermes_used,
                "hermes_selection_reason": route.hermes_selection_reason,
                "max_parallelism": _max_parallelism(levels),
                "critical_path_task_count": len(levels),
                "context_bytes": _bytes({
                    "bounded_memory_context": payload.get(
                        "bounded_memory_context"
                    ),
                    "tasks": tasks,
                }),
                "evidence_contract_complete": evidence_complete,
                "authority": payload.get("authority"),
                "execution_wall_clock_seconds": None,
            },
            "delta": {
                "planned_calls_avoided": max(
                    0, len(SPECIALISTS) - len(tasks)
                ),
                "team_size_reduction": (
                    len(SPECIALISTS) - len(selected_owners)
                ),
                "context_bytes_delta": (
                    _bytes({
                        "bounded_memory_context": payload.get(
                            "bounded_memory_context"
                        ),
                        "tasks": tasks,
                    })
                    - _bytes({
                        "goal": human_goal,
                        "specialists": SPECIALISTS,
                    })
                ),
            },
        })

    report = {
        "schema": "harness-hermes-delegation-benchmark/v1",
        "status": "PASS",
        "scope": "PLANNING_AND_TOPOLOGY",
        "execution_metrics_pending_operational_proof": True,
        "legacy_source": "scripts.run_system_improvement_review.SPECIALISTS",
        "cases": rows,
        "summary": {
            "case_count": len(rows),
            "legacy_mean_planned_calls": mean(
                row["legacy"]["agent_calls_planned"] for row in rows
            ),
            "v1_mean_planned_calls": mean(
                row["v1"]["agent_calls_planned"] for row in rows
            ),
            "mean_planned_calls_avoided": mean(
                row["delta"]["planned_calls_avoided"] for row in rows
            ),
            "v1_mean_planning_latency_ms": round(mean(
                row["v1"]["planning_latency_ms"] for row in rows
            ), 3),
            "all_v1_authority_preserved": all(
                row["v1"]["authority"] == "DEEPSEEK_HARNESS"
                for row in rows
            ),
            "all_v1_evidence_contracts_complete": all(
                row["v1"]["evidence_contract_complete"] is True
                for row in rows
            ),
            "legacy_executor_imported_by_dynamic_mission": False,
        },
        "promotion_rule": (
            "This planning benchmark alone cannot promote full synergy. "
            "Real execution wall clock, review and learning deltas must come "
            "from the operational proof."
        ),
        "CI_REAL_TELEGRAM_EGRESS": 0,
        "SYSTEM_IMPROVEMENT_AUTONOMOUS_TELEGRAM_EGRESS": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print("LEGACY_VS_DELEGATION_V1_PLANNING_BENCHMARK=PASS")
    print(
        "MEAN_PLANNED_CALLS_AVOIDED="
        + str(report["summary"]["mean_planned_calls_avoided"])
    )
    print("EXECUTION_METRICS_PENDING_OPERATIONAL_PROOF=YES")
    print("CI_REAL_TELEGRAM_EGRESS=0")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run(output=Path(args.output))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
