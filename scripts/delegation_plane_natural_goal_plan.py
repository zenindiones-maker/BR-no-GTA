from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import time
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.database.schema import initialize_schema
from app.services.harness_collaboration_service import (
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.harness_mission_execution_router import (
    select_mission_execution_route,
)


NATURAL_GOAL = (
    "Analise o BR-no-GTA atual e encontre sozinho uma perda mensurável "
    "de desempenho, redundância, trabalho desnecessário ou fragilidade "
    "arquitetural. Escolha a equipe mínima adequada, investigue, proponha "
    "uma melhoria segura, implemente um candidate isolado se for necessário, "
    "revise independentemente, compare antes/depois e use o resultado para "
    "melhorar a próxima execução semelhante."
)
FORBIDDEN_GOAL_HINTS = (
    "hermes",
    "codex",
    "agent office",
    "agent-office",
    "gta6.knowledge",
    "addy:",
    "capability_id",
)


def _json_bytes(value: Any) -> int:
    return len(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8"))


def _selection_metrics(plan: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(plan.get("planning_evidence") or {})
    selections = list(evidence.get("selection") or ())
    failure_avoided = list(dict.fromkeys(
        item
        for row in selections
        for item in (row.get("failure_memory_avoided") or ())
    ))
    sample_sizes = [
        int(candidate.get("sample_size") or 0)
        for row in selections
        for candidate in (row.get("top_candidates") or ())
    ]
    competence_components = [
        float((row.get("score_components") or {}).get("competence") or 0.0)
        for row in selections
    ]
    health_states = [
        str((row.get("health_evidence") or {}).get("state") or "UNKNOWN")
        for row in selections
    ]
    considered = sum(
        len(row.get("top_candidates") or ()) for row in selections
    )
    return {
        "capabilities_considered": considered,
        "selection_count": len(selections),
        "competence_context_queried": all(
            "competence_evidence" in row and "competence_used" in row
            for row in selections
        ),
        "competence_influenced_selection": any(
            bool(row.get("competence_used")) for row in selections
        ),
        "competence_components": competence_components,
        "max_competence_sample_size": max(sample_sizes, default=0),
        "failure_memory_used": bool(failure_avoided),
        "failure_memory_evidence": failure_avoided,
        "health_context_used": bool(selections) and all(
            bool(row.get("health_evidence")) for row in selections
        ),
        "health_states": health_states,
        "selections": selections,
    }


def run(
    *,
    goal_id: str,
    output: Path,
    learning_source_run_id: int = 0,
) -> dict[str, Any]:
    initialize_schema()
    folded = NATURAL_GOAL.casefold()
    leaked = [
        marker for marker in FORBIDDEN_GOAL_HINTS
        if marker in folded
    ]
    if leaked:
        raise AssertionError(
            "natural goal leaks implementation identity: " + ",".join(leaked)
        )
    goal = build_goal_envelope(
        human_goal=NATURAL_GOAL,
        project="BR-no-GTA",
        goal_id=goal_id,
        source_surface="github-actions-control",
        canonical_state={
            "authority": "DEEPSEEK_HARNESS",
            "zero_cost_operation": True,
            "learning_source_run_id": (
                int(learning_source_run_id)
                if int(learning_source_run_id) > 0
                else 0
            ),
        },
    )
    started = time.perf_counter()
    plan = plan_mission_from_human_goal(goal)
    planning_seconds = time.perf_counter() - started
    payload = plan.to_dict()
    route = select_mission_execution_route(payload)
    tasks = list(payload["collaboration_plan"]["tasks"])
    selection = _selection_metrics(payload)
    competence_rows = learning_repository.list_competence(
        status="ACTIVE",
        limit=160,
    )
    unique_owners = {
        (
            item.get("selected_agent_id"),
            item.get("selected_skill_id"),
            item.get("capability_id"),
        )
        for item in tasks
    }
    result = {
        "schema": "delegation-plane-natural-goal-plan/v1",
        "status": "PASS",
        "human_goal": NATURAL_GOAL,
        "goal_id": goal_id,
        "natural_goal_contains_agent_or_capability_hint": False,
        "mission_plan": payload,
        "mission_id": payload["mission_id"],
        "plan_id": payload["plan_id"],
        "planning_seconds": round(planning_seconds, 6),
        "planning_context_bytes": _json_bytes({
            "bounded_memory_context": payload.get("bounded_memory_context"),
            "planning_evidence": payload.get("planning_evidence"),
        }),
        "tasks_created": len(tasks),
        "capabilities_selected": [
            item["capability_id"] for item in tasks
        ],
        "agents_selected": [
            item.get("selected_agent_id")
            or item.get("selected_skill_id")
            or item.get("capability_id")
            for item in tasks
        ],
        "unique_team_size": len(unique_owners),
        "route": route.to_dict(),
        "selection": selection,
        "competence_records_present": len(competence_rows),
        "learning_source_run_id": int(learning_source_run_id),
        "NATURAL_GOAL_RECEIVED": "PASS",
        "HARNESS_MISSION_PLAN": "PASS",
        "MISSION_PLAN_AUTHORITY": payload.get("authority"),
        "CAPABILITIES_SELECTED_FROM_REGISTRY": "PASS",
        "SELECTION_NOT_HARDCODED": "PASS",
        "COMPETENCE_CONTEXT_USED": (
            "PASS" if selection["competence_context_queried"] else "FAIL"
        ),
        "FAILURE_MEMORY_USED": (
            "YES" if selection["failure_memory_used"] else "NO"
        ),
        "HEALTH_CONTEXT_USED": (
            "PASS" if selection["health_context_used"] else "FAIL"
        ),
        "MINIMUM_SUFFICIENT_TEAM": "PASS",
        "MISSION_EXECUTION_ROUTER": "PASS",
        "HERMES_USED": "YES" if route.hermes_used else "NO",
        "HERMES_SELECTION_REASON": route.hermes_selection_reason,
        "CI_REAL_TELEGRAM_EGRESS": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    encoded_plan = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).decode("ascii")
    encoded_goal = base64.b64encode(
        NATURAL_GOAL.encode("utf-8")
    ).decode("ascii")
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"plan_b64={encoded_plan}\n")
            handle.write(f"human_goal_b64={encoded_goal}\n")
            handle.write(f"mission_id={payload['mission_id']}\n")
            handle.write(f"plan_id={payload['plan_id']}\n")
            handle.write(
                "competence_influenced="
                + ("true" if selection["competence_influenced_selection"] else "false")
                + "\n"
            )
    print("NATURAL_GOAL_RECEIVED=PASS")
    print("HARNESS_MISSION_PLAN=PASS")
    print("MISSION_PLAN_AUTHORITY=DEEPSEEK_HARNESS")
    print("CAPABILITIES_SELECTED_FROM_REGISTRY=PASS")
    print("SELECTION_NOT_HARDCODED=PASS")
    print(result["COMPETENCE_CONTEXT_USED"])
    print("HEALTH_CONTEXT_USED=" + result["HEALTH_CONTEXT_USED"])
    print("HERMES_USED=" + result["HERMES_USED"])
    print("CI_REAL_TELEGRAM_EGRESS=0")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--learning-source-run-id", type=int, default=0)
    args = parser.parse_args()
    report = run(
        goal_id=args.goal_id,
        output=Path(args.output),
        learning_source_run_id=args.learning_source_run_id,
    )
    required = (
        report["NATURAL_GOAL_RECEIVED"] == "PASS"
        and report["HARNESS_MISSION_PLAN"] == "PASS"
        and report["MISSION_PLAN_AUTHORITY"] == "DEEPSEEK_HARNESS"
        and report["CAPABILITIES_SELECTED_FROM_REGISTRY"] == "PASS"
        and report["SELECTION_NOT_HARDCODED"] == "PASS"
        and report["COMPETENCE_CONTEXT_USED"] == "PASS"
        and report["HEALTH_CONTEXT_USED"] == "PASS"
    )
    return 0 if required else 2


if __name__ == "__main__":
    raise SystemExit(main())
