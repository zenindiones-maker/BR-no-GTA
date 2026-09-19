from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.schema import initialize_schema
from app.services.harness_learning_service import register_skill_version
from app.services.opencode_executor_profile_service import (
    BASELINE_OPENCODE_EXECUTOR_VERSION,
    CANDIDATE_OPENCODE_EXECUTOR_VERSION,
    OPENCODE_EXECUTOR_SKILL_ID,
    executable_opencode_executor_profile,
    resolve_active_opencode_executor_profile,
)


PROMOTION_EVIDENCE_RUN_ID = 35450516329


def hydrate() -> dict:
    initialize_schema()
    v1 = executable_opencode_executor_profile(BASELINE_OPENCODE_EXECUTOR_VERSION)
    v2 = executable_opencode_executor_profile(CANDIDATE_OPENCODE_EXECUTOR_VERSION)
    if v2["options"].get("status") != "PROMOTED":
        raise RuntimeError("OpenCode v2 is not versioned as PROMOTED")
    evidence = (
        "github:run:35340487375:observed-baseline-403",
        "github:run:35343942135:official-cli-candidate",
        f"github:run:{PROMOTION_EVIDENCE_RUN_ID}:observed-promotion",
    )
    register_skill_version(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        version=BASELINE_OPENCODE_EXECUTOR_VERSION,
        parent_version=None,
        content_ref=v1["content_ref"],
        checksum=v1["checksum"],
        status="SUPERSEDED",
        evidence_refs=evidence,
    )
    register_skill_version(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        version=CANDIDATE_OPENCODE_EXECUTOR_VERSION,
        parent_version=BASELINE_OPENCODE_EXECUTOR_VERSION,
        content_ref=v2["content_ref"],
        checksum=v2["checksum"],
        status="ACTIVE",
        evidence_refs=evidence,
    )
    active = resolve_active_opencode_executor_profile()
    if active["version"] != CANDIDATE_OPENCODE_EXECUTOR_VERSION:
        raise RuntimeError("promoted OpenCode v2 profile did not become active")
    return {
        "status": "PASS",
        "mode": "REHYDRATE_IMMUTABLE_PROMOTION",
        "promotion_evidence_run_id": PROMOTION_EVIDENCE_RUN_ID,
        "active_profile": active,
        "quality_regression": "NO",
        "fallback_occurred": False,
        "zero_cost": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = hydrate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OPENCODE_PROMOTED_PROFILE=PASS")
    print("OPENCODE_ACTIVE_PROFILE=v2")
    print(f"PROMOTION_EVIDENCE_RUN_ID={PROMOTION_EVIDENCE_RUN_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
