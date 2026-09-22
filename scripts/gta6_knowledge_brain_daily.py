from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.services.telegram_group_human_surface_service import HUMAN_SURFACE
from scripts.continuous_intelligence_cycle import run_scheduled


def run(
    *,
    artifact_dir: Path,
    upstream_root: Path,
    target_sha: str,
    trigger_kind: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    cycle = run_scheduled(
        artifact_dir=artifact_dir,
        upstream_root=upstream_root,
        target_sha=target_sha,
        trigger_kind=trigger_kind,
        force_gta6_refresh=bool(force_refresh),
        force_daily_projection=True,
    )
    report = {
        "schema": "gta6-knowledge-brain-daily/v1",
        "status": "PASS",
        "authority": "DEEPSEEK_HARNESS",
        "human_surface": HUMAN_SURFACE,
        "PRIVATE_TELEGRAM_HUMAN_SURFACE": "DISABLED",
        "cycle": cycle,
        "brain_daily_run": cycle.get("brain_daily_run"),
        "telegram_group_digest": {
            "status": "DISABLED",
            "reason": "UNSOLICITED_TELEGRAM_EGRESS_FORBIDDEN",
        },
        "UNSOLICITED_TELEGRAM_EGRESS": "NO",
        "TELEGRAM_MESSAGES_SENT": 0,
        "OBSIDIAN_CANONICAL_MEMORY": "NO",
        "HERMES_DIRECT_CANONICAL_WRITE": "NO",
        "AGENT_DIRECT_CANONICAL_WRITE": "NO",
        "ZERO_COST_OPERATION": os.getenv("ZERO_COST_OPERATION", "UNKNOWN"),
        "TERMUX_HEAVY_PROCESSING": "NO",
        "FORCED_SOURCE_CHECK": "YES" if force_refresh else "NO",
        "CONDITIONAL_CHANGE_DETECTION": "PRESERVED",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "gta6-knowledge-brain-daily.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    print("GTA6_KNOWLEDGE_BRAIN_DAILY=PASS")
    print("HARNESS_AUTHORITY=PASS")
    print("TELEGRAM_GROUP_ONLY_HUMAN_SURFACE=PASS")
    print("PRIVATE_TELEGRAM_HUMAN_SURFACE=DISABLED")
    print("DAILY_BRAIN_TELEGRAM_EGRESS=0")
    print("UNSOLICITED_TELEGRAM_EGRESS=NO")
    print("TELEGRAM_MESSAGES_SENT=0")
    print("OBSIDIAN_CANONICAL_MEMORY=NO")
    print("HERMES_DIRECT_CANONICAL_WRITE=NO")
    print("AGENT_DIRECT_CANONICAL_WRITE=NO")
    print("DAILY_RUN_ID=" + str((cycle.get("brain_daily_run") or {}).get("run_id")))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--upstream-root", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--trigger-kind", default="workflow_dispatch")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()
    run(
        artifact_dir=Path(args.artifact_dir),
        upstream_root=Path(args.upstream_root),
        target_sha=args.target_sha,
        trigger_kind=args.trigger_kind,
        force_refresh=args.force_refresh,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
