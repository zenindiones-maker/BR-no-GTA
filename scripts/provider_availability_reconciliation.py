from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.database.schema import initialize_schema
from app.services.provider_availability_reconciliation_service import (
    ProviderAvailabilityReconciler,
)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _github_output(key: str, value: object) -> None:
    target = str(os.getenv("GITHUB_OUTPUT") or "").strip()
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def run(*, wait_file: Path, output_dir: Path) -> dict:
    initialize_schema()
    wait = json.loads(wait_file.read_text(encoding="utf-8"))
    reconciler = ProviderAvailabilityReconciler()
    result = reconciler.reconcile(
        wait=wait,
        artifact_dir=output_dir,
    )
    _write_json(
        output_dir / "provider-availability-reconciliation-result.json",
        result,
    )
    next_wait = dict(result.get("next_wait") or {})
    if next_wait:
        _write_json(
            output_dir / "provider-availability-next-wait.json",
            next_wait,
        )

    decision = str(result.get("decision") or "")
    print(f"PROVIDER_RECONCILIATION_DECISION={decision}")
    print(
        "RECONCILIATION_NO_STATE_CHANGE="
        + str(result.get("RECONCILIATION_NO_STATE_CHANGE"))
    )
    print(
        "NO_PROVIDER_CALL_ON_UNCHANGED_POOL="
        + str(result.get("NO_PROVIDER_CALL_ON_UNCHANGED_POOL"))
    )
    print(
        "NEW_EFFECTIVE_PROVIDER_COUNT="
        + str(result.get("new_effective_count"))
    )
    print(
        "PROVIDER_RECOVERY_EPOCH="
        + str(
            (result.get("provider_recovery_epoch") or {}).get("epoch_id")
            or ""
        )
    )
    print("MISSION_TERMINAL=FALSE")
    print(
        "HUMAN_INTERVENTION_REQUIRED="
        + (
            "TRUE"
            if bool(result.get("human_intervention_required"))
            else "FALSE"
        )
    )
    _github_output("decision", decision)
    _github_output(
        "mission_id",
        str(result.get("mission_id") or ""),
    )
    _github_output(
        "task_id",
        str(result.get("task_id") or ""),
    )
    _github_output(
        "state_changed",
        str(bool(result.get("state_changed"))).lower(),
    )
    _github_output(
        "new_effective_count",
        int(result.get("new_effective_count") or 0),
    )
    _github_output(
        "recovery_epoch",
        str(
            (result.get("provider_recovery_epoch") or {}).get("epoch_id")
            or ""
        ),
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        wait_file=args.wait_file,
        output_dir=args.output_dir,
    )
    decision = str(result.get("decision") or "")
    if decision not in {
        "STILL_WAITING",
        "REQUEUE_TASK",
        "STRUCTURAL_BLOCK",
        "EXTERNAL_GATE",
    }:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
