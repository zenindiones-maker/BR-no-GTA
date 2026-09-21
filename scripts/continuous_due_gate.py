from __future__ import annotations

from datetime import datetime, timezone
import argparse
from pathlib import Path
import os

from app.database import continuous_operation_repository as repository
from app.database.schema import initialize_schema
from app.services.continuous_operation_policy_service import load_continuous_operation_policy


def _age_seconds(kind: str) -> float | None:
    rows = repository.list_cycle_runs(cycle_kind=kind, limit=1)
    if not rows:
        return None
    stamp = str(rows[0].get("finished_at") or rows[0].get("started_at") or "")
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


def due_state() -> dict[str, bool]:
    initialize_schema()
    policy = load_continuous_operation_policy()
    mapping = {
        "gta6_due": ("GTA6_INTELLIGENCE", "gta6_delta_scan_seconds"),
        "daily_due": ("DAILY_CONSOLIDATION", "daily_consolidation_seconds"),
        "improvement_due": ("SYSTEM_IMPROVEMENT", "system_improvement_seconds"),
        "weekly_due": ("WEEKLY_AUDIT", "weekly_audit_seconds"),
    }
    result: dict[str, bool] = {}
    for key, (cycle_kind, cadence_key) in mapping.items():
        age = _age_seconds(cycle_kind)
        result[key] = age is None or age >= int(policy.cadence[cadence_key])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    args = parser.parse_args()
    state = due_state()
    for key, value in state.items():
        print(f"{key.upper()}={'YES' if value else 'NO'}")
    if args.github_output:
        path = Path(args.github_output)
        with path.open("a", encoding="utf-8") as handle:
            for key, value in state.items():
                handle.write(f"{key}={'true' if value else 'false'}\n")
    print("CONTINUOUS_DUE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
