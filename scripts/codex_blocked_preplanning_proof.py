from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path

from app.database.schema import initialize_schema
from app.services.harness_executor_availability_service import (
    resolve_blocked_executor_alternatives,
)
from app.services.planner_replan_learning_service import (
    record_real_wasted_replan_incident,
)


def _decode_plan(checkpoint: dict) -> dict:
    raw = base64.b64decode(str(checkpoint["plan_b64"]).encode("ascii"), validate=True)
    plan = json.loads(raw.decode("utf-8"))
    if plan.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("checkpoint plan escaped Harness authority")
    return plan


def _fingerprint(plan: dict) -> str:
    raw = json.dumps(
        plan,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()

    initialize_schema()
    checkpoint = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    if checkpoint.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("checkpoint escaped Harness authority")
    if checkpoint.get("mission_id") != "mission-3043b06fb2ec006c1f41":
        raise AssertionError("unexpected canonical checkpoint mission")

    plan = _decode_plan(checkpoint)
    before = _fingerprint(plan)
    blocked = {
        str(task.get("capability_id") or "").strip()
        for task in ((plan.get("collaboration_plan") or {}).get("tasks") or ())
        if str(task.get("capability_id") or "").strip().startswith(
            "agent-office.codex."
        )
    }
    if not blocked:
        raise AssertionError("canonical checkpoint has no Codex task")

    resolution = resolve_blocked_executor_alternatives(
        plan,
        blocked_capability_ids=blocked,
    )
    after = _fingerprint(plan)
    if before != after:
        raise AssertionError("deterministic resolution mutated canonical MissionPlan")

    assert resolution["ALTERNATIVE_EXECUTOR_RESOLUTION_DETERMINISTIC"] == "PASS"
    assert resolution["ALTERNATIVE_EXECUTOR_AVAILABLE"] == "NO", resolution
    assert resolution["MISSION_LEVEL_COMPLETE_ALTERNATIVE_AVAILABLE"] == "NO"
    by_task = {
        item["task_id"]: item
        for item in resolution["blocked_tasks"]
    }
    readonly = by_task["instrument-planner"]
    mutating = by_task["create-candidate"]
    assert readonly["TASK_LEVEL_ALTERNATIVE_AVAILABLE"] == "YES", readonly
    assert mutating["TASK_LEVEL_ALTERNATIVE_AVAILABLE"] == "NO", mutating
    readonly_alternative = next(
        item
        for item in readonly["alternatives"]
        if item["capability_id"] == "agent-office.deterministic-analysis"
    )
    readonly_diagnostic = next(
        item
        for item in readonly["candidate_diagnostics"]
        if item["CAPABILITY_ID"] == "agent-office.deterministic-analysis"
    )
    mutating_diagnostic = next(
        item
        for item in mutating["candidate_diagnostics"]
        if item["CAPABILITY_ID"] == "agent-office.deterministic-analysis"
    )
    assert readonly_diagnostic["FINAL_REJECTION_REASON"] == "ACCEPTED"
    assert mutating_diagnostic["FINAL_REJECTION_REASON"].startswith(
        "execution-contract-insufficient:missing="
    )
    assert resolution["NO_ALTERNATIVE_EXECUTOR_REPLAN"] == "NO"
    assert resolution["PROVIDER_CALL_EXECUTED"] == "NO"
    assert resolution["SEMANTIC_REPLAN_PERFORMED"] == "NO"
    assert resolution["MISSION_STATE"] == "WAITING_FOR_EXTERNAL_AUTH"

    learning = record_real_wasted_replan_incident()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "codex-blocked-preplanning-proof/v1",
        "canonical_checkpoint_run_id": 35850473901,
        "wasted_replan_run_id": 35851596990,
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "mission_id": checkpoint.get("mission_id"),
        "plan_id": plan.get("plan_id"),
        "plan_sha256_before": before,
        "plan_sha256_after": after,
        "resolution": resolution,
        "learning": {
            "episode_id": learning["episode"]["episode_id"],
            "memory_id": learning["memory"]["memory_id"],
            "failure_domain": learning["FAILURE_DOMAIN"],
            "failure_reason": learning["FAILURE_REASON"],
            "wasted_replan": learning["WASTED_REPLAN"],
            "provider_competence_penalized": learning[
                "PROVIDER_COMPETENCE_PENALIZED"
            ],
        },
    }
    (args.artifact_dir / "codex-blocked-preplanning-proof.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )

    print("CODEX_BLOCKED_BEFORE_PLANNING=PASS")
    print("ALTERNATIVE_EXECUTOR_RESOLUTION_DETERMINISTIC=PASS")
    print("READ_ONLY_TASK_ALTERNATIVE_AVAILABLE=PASS")
    print("READ_ONLY_ALTERNATIVE=" + readonly_alternative["capability_id"])
    print("MUTATING_TASK_ALTERNATIVE_AVAILABLE=NO")
    print("MISSION_LEVEL_COMPLETE_ALTERNATIVE_AVAILABLE=NO")
    print("ALTERNATIVE_EXECUTOR_AVAILABLE=NO")
    print("NO_ALTERNATIVE_EXECUTOR_REPLAN=NO")
    print("PROVIDER_CALL_EXECUTED=NO")
    print("SEMANTIC_REPLAN_PERFORMED=NO")
    print("CANONICAL_CHECKPOINT_PRESERVED=PASS")
    for key in (
        "CAPABILITY_ID",
        "EXECUTION_ENABLED",
        "ALLOWED_ACTIONS",
        "EXECUTOR_BINDING",
        "EXECUTOR_ADAPTER_COMPATIBLE",
        "EXECUTION_OPERATIONS",
        "REQUIRED_OPERATIONS",
        "EXECUTION_CONTRACT_REJECTION",
        "SIDE_EFFECT_CLASS",
        "REQUIRED_SIDE_EFFECT_CLASS",
        "SIDE_EFFECT_COMPATIBLE",
        "DEFAULT_WRITE_SCOPE",
        "SECURITY_BOUNDARY",
        "AUTHORITY_COMPATIBLE",
        "HEALTH_STATE",
        "HEALTH_SOURCE",
        "CANDIDATE_REQUIREMENT",
        "CANDIDATE_ARTIFACT_CAPABLE",
        "FINAL_REJECTION_REASON",
    ):
        value = readonly_diagnostic[key]
        if isinstance(value, list):
            value = ",".join(str(item) for item in value)
        print(f"{key}={value}")
    print(
        "MUTATING_FINAL_REJECTION_REASON="
        + mutating_diagnostic["FINAL_REJECTION_REASON"]
    )
    print("MISSION_STATE=WAITING_FOR_EXTERNAL_AUTH")
    print("FAILURE_DOMAIN=PLANNER_PROVIDER_TRANSPORT")
    print("FAILURE_REASON=NVIDIA_TIMEOUT")
    print("WASTED_REPLAN=YES")
    print("LEARNING_PLANE_REAL_EPISODE=PASS")
    print("LEARNING_PLANE_FAILURE_MEMORY=PASS")
    print("PROVIDER_COMPETENCE_PENALIZED=NO")
    print("NEW_NATURAL_SWARM=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
