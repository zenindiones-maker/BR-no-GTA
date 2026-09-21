from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.database.schema import initialize_schema
from app.services.telegram_system_improvement_dispatch_service import (
    dispatch_telegram_system_improvement_mission,
)


def resume_from_ingress(path: Path) -> dict:
    ingress = json.loads(path.read_text(encoding="utf-8"))
    plan = dict(ingress["plan"])
    previous = dict(ingress["canonical_result"])
    literal = str(ingress["literal_human_input"])
    mission_plan = dict(plan["mission_plan"])

    initialize_schema()
    resumed = dispatch_telegram_system_improvement_mission(
        plan=plan,
        state={
            "active_goal_id": plan.get("active_goal_id"),
            "telegram_chat_id": 0,
        },
        message=literal,
    )

    if resumed.get("mission_id") != previous.get("mission_id"):
        raise PermissionError("resume drifted from original mission_id")
    if resumed.get("plan_id") != previous.get("plan_id"):
        raise PermissionError("resume drifted from original plan_id")
    if mission_plan.get("mission_id") != previous.get("mission_id"):
        raise PermissionError("checkpoint MissionPlan lineage mismatch")
    if mission_plan.get("plan_id") != previous.get("plan_id"):
        raise PermissionError("checkpoint plan lineage mismatch")

    result = {
        **ingress,
        "previous_child_run_id": ingress.get("child_run_id"),
        "child_run_id": int(resumed["run_id"]),
        "canonical_result": resumed,
        "mission_plan_reused": True,
        "mission_replanned": False,
    }
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingress", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    result = resume_from_ingress(args.ingress)
    child_run_id = int(result["child_run_id"])
    output = args.github_output
    if output is None:
        raw = os.getenv("GITHUB_OUTPUT", "").strip()
        output = Path(raw) if raw else None
    if output is not None:
        with output.open("a", encoding="utf-8") as fh:
            fh.write(f"child_run_id={child_run_id}\n")
            fh.write(f"mission_id={result['canonical_result']['mission_id']}\n")
            fh.write(f"plan_id={result['canonical_result']['plan_id']}\n")

    print("EXISTING_MISSION_PLAN_REUSED=PASS")
    print("MISSION_REPLANNED=NO")
    print("MISSION_ID_PRESERVED=PASS")
    print("PLAN_ID_PRESERVED=PASS")
    print(f"DYNAMIC_CHILD_RUN_ID={child_run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
