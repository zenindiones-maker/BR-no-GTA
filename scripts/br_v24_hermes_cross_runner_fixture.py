#!/usr/bin/env python3
"""Prove Hermes' existing TaskResultEnvelope survives real GitHub job boundary.

Uses a synthetic, non-sensitive task receipt, not a real Hermes/SLM mission.
The repository's ORIGINAL runtime.export/restore and envelope loaders are used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


WORKFLOW = "BR V24 Hermes Cross Runner Dependency Artifact"
REPO = "zenindiones-maker/BR-no-GTA"
BRANCH = "work/br-slm-agent-reconstruction-v24"
MISSION_ID = "br-v24-hermes-cross-runner-fixture"
CAPABILITY_ID = "agent-office.deterministic-analysis"
PRIMARY_ID = "retrieve-primary"


def spec(sha: str):
    return SimpleNamespace(
        mission_id=MISSION_ID,
        goal_id="verify-durable-task-result-handoff",
        base_sha=sha,
        allowed_task_ids=(PRIMARY_ID, "retrieve-dependent"),
        allowed_capability_ids=(CAPABILITY_ID,),
    )


def environment_ok(env: dict, phase: str):
    return (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_WORKFLOW") == WORKFLOW
        and env.get("GITHUB_REPOSITORY") == REPO
        and env.get("GITHUB_REF_NAME") == BRANCH
        and env.get("GITHUB_JOB") == ("export" if phase == "a" else "restore")
        and not env.get("PREFIX", "").startswith("/data/data/com.termux/")
    )


def execute(phase, checkpoint: Path):
    if phase not in {"a", "b"} or not environment_ok(os.environ, phase):
        raise PermissionError("BR_HERMES_CROSS_RUNNER_REMOTE_ONLY")
    root=Path(__file__).resolve().parents[1]
    current=subprocess.check_output(["git","rev-parse","HEAD"], cwd=root,text=True).strip()
    if current != os.environ.get("GITHUB_SHA"):
        raise PermissionError("BR_HERMES_CROSS_RUNNER_HEAD_DRIFT")
    temp=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    cp=checkpoint.resolve(strict=False)
    if cp.parent != temp or cp.is_symlink():
        raise PermissionError("BR_HERMES_CROSS_RUNNER_CHECKPOINT_OUTSIDE_RUNNER_TEMP")
    sys.path.insert(0,str(root))
    from app.services.task_result_envelope_service import (
        build_task_result_envelope, persist_task_result_envelope, load_task_result_envelope,
    )
    from app.services.hermes_multiagent.runtime import (
        export_hermes_mission_checkpoint, restore_hermes_mission_checkpoint,
    )
    local=temp/("br-v24-hermes-phase-"+phase)
    if local.exists():
        raise RuntimeError("BR_HERMES_CROSS_RUNNER_NOT_FRESH")
    local.mkdir(mode=0o700)
    home=local/"hermes-home"
    home.mkdir(mode=0o700)
    artifacts=local/"artifacts"
    artifacts.mkdir(mode=0o700)
    now=datetime.now(timezone.utc).isoformat()
    if phase=="a":
        envelope=build_task_result_envelope(
            mission_id=MISSION_ID,
            task_id=PRIMARY_ID,
            capability_id=CAPABILITY_ID,
            agent_id="deterministic-analysis",
            skill_id=None,
            executor_binding="app.services.agent_office_harness_service.execute_agent_office_deterministic_analysis",
            status="EXECUTED",
            started_at=now,
            completed_at=now,
            elapsed_ms=0.0,
            result={"summary":"fixture-only durable primary result", "evidence_refs": ["fixture:owned-no-private-data"]},
            source_task_ids=(),
            authorization_id="fixture-no-real-authorization",
        )
        persisted=persist_task_result_envelope(envelope,artifact_dir=artifacts,index=1)
        manifest=export_hermes_mission_checkpoint(
            spec=spec(current), hermes_home=home, artifact_dir=artifacts,
            checkpoint_dir=cp,
        )
        if len(manifest.get("task_result_files") or ()) != 1:
            raise RuntimeError("BR_HERMES_CROSS_RUNNER_EXPORT_MISSING")
        if len(manifest.get("result_files") or ()) != 0:
            raise RuntimeError("BR_HERMES_CROSS_RUNNER_UNEXPECTED_CAPABILITY_RESULTS")
        print("BR_HERMES_CROSS_RUNNER_TASKRESULT_PERSISTED=PASS")
        print("BR_HERMES_CROSS_RUNNER_SHA256="+envelope.content_sha256)
    else:
        if not cp.is_dir():
            raise RuntimeError("BR_HERMES_CROSS_RUNNER_DOWNLOADED_CHECKPOINT_MISSING")
        restored=restore_hermes_mission_checkpoint(
            spec=spec(current), checkpoint_dir=cp, hermes_home=home,
            artifact_dir=artifacts,
        )
        original=cp/"task-results/retrieve-primary-1.json"
        recovered=artifacts/"task-results/retrieve-primary-1.json"
        if original.read_bytes()!=recovered.read_bytes():
            raise RuntimeError("BR_HERMES_CROSS_RUNNER_COPIED_BYTES_CHANGED")
        payload=load_task_result_envelope(
            artifact_dir=artifacts,
            task_result_ref="artifact:task-results/retrieve-primary-1.json",
        )
        if (restored.get("CANONICAL_CHECKPOINT_RESTORED")!="PASS"
             or payload.get("mission_id")!=MISSION_ID
             or payload.get("task_id")!=PRIMARY_ID
             or payload.get("status")!="EXECUTED"
             or payload.get("result_summary")!="fixture-only durable primary result"):
            raise RuntimeError("BR_HERMES_CROSS_RUNNER_ENVELOPE_INVALID")
        print("BR_HERMES_CROSS_RUNNER_TASKRESULT_RESTORED=PASS")
        print("BR_HERMES_CROSS_RUNNER_DEPENDENCY_BYTES=PASS")
        print("BR_HERMES_CROSS_RUNNER_FULL_MISSION_EXECUTION=NOT_ATTEMPTED")
        print("BR_HERMES_CROSS_RUNNER_PRODUCTION_PROMOTION=BLOCKED")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--phase",choices=("a","b"),required=True)
    p.add_argument("--checkpoint",type=Path,required=True)
    args=p.parse_args()
    execute(args.phase,args.checkpoint)


if __name__=="__main__":
    main()
