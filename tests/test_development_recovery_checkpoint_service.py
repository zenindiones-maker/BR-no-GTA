from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from app.services.development_recovery_checkpoint_service import (
    CheckpointBlocked,
    CheckpointConflict,
    DevelopmentRecoveryCheckpointService,
)


def run(cwd: Path, *args: str, env=None) -> str:
    cp = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True, env=env)
    return cp.stdout.strip()


def init_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git","init","--bare",str(remote)],check=True,capture_output=True)
    subprocess.run(["git","init",str(repo)],check=True,capture_output=True)
    run(repo,"git","config","user.email","test@example.invalid")
    run(repo,"git","config","user.name","Test")
    (repo/"app").mkdir()
    (repo/"tests").mkdir()
    (repo/"app"/"base.py").write_text("BASE = 1\n")
    run(repo,"git","add","app/base.py")
    run(repo,"git","commit","-m","base")
    run(repo,"git","branch","-M","work/gate6f-analytics-learning")
    run(repo,"git","remote","add","origin",str(remote))
    run(repo,"git","push","-u","origin","work/gate6f-analytics-learning")
    return repo, remote


def ledger(repo: Path, base: str, seq: int = 0):
    return {
      "schema_version":"DevelopmentProgressLedger/v1",
      "mission_id":"m1","goal_digest":"1"*64,
      "canonical_branch":"work/gate6f-analytics-learning",
      "canonical_base_sha":base,
      "recovery_ref":"recovery/dev/m1",
      "latest_verified_checkpoint_id":None,
      "latest_verified_checkpoint_sha":None,
      "checkpoint_sequence":seq,
      "plan_steps":["a","b"],"completed_steps":["a"],"current_step":"b","next_step":None,
      "open_blockers":[],"decisions":[],"rejected_directions":[],"known_failures":[],
      "validation_state":"RED_ALLOWED",
      "tests":{"targeted":"RED","affected_subgraph":"NOT_RUN","root":"NOT_RUN"},
      "evidence_refs":[],"artifact_refs":[],"do_not_repeat":["a"],
      "side_effects":{"known_completed":[],"unknown_requires_reconciliation":[]},
      "updated_at":"2026-10-01T15:00:00+00:00"
    }


def test_shadow_index_untracked_red_checkpoint_readback_and_dedupe(tmp_path: Path):
    repo,_ = init_repo(tmp_path)
    base = run(repo,"git","rev-parse","HEAD")
    (repo/"app"/"base.py").write_text("BASE = 2\n")
    (repo/"tests"/"test_new.py").write_text("def test_red():\n    assert False\n")
    run(repo,"git","add","app/base.py")
    active_index_before = run(repo,"git","write-tree")
    status_before = run(repo,"git","status","--porcelain=v1","-uall")

    service = DevelopmentRecoveryCheckpointService(repo)
    first = service.persist(
        ledger=ledger(repo,base),
        mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt1", agent_execution_identity="agent1", authorization_id="auth1",
        included_paths=["app","tests"], excluded_paths=[],
    )
    assert first["remote_write_status"] == "COMPLETE"
    assert first["remote_readback_status"] == "VERIFIED"
    assert first["development_state"] == "DURABLE"
    assert first["recovery_commit_sha"] == run(repo,"git","ls-remote","origin","refs/heads/recovery/dev/m1").split()[0]
    assert run(repo,"git","write-tree") == active_index_before
    assert run(repo,"git","status","--porcelain=v1","-uall") == status_before

    second = service.persist(
        ledger=ledger(repo,base),
        mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt1", agent_execution_identity="agent1", authorization_id="auth1",
        included_paths=["app","tests"], excluded_paths=[],
    )
    assert second["checkpoint_write"] == "SKIPPED_UNCHANGED"
    assert second["recovery_commit_sha"] == first["recovery_commit_sha"]
    assert second["development_state"] == "DURABLE"
    assert second["remote_write_status"] == "COMPLETE"
    assert second["remote_readback_status"] == "VERIFIED"


def test_secret_candidate_blocks_without_silent_drop(tmp_path: Path):
    repo,_ = init_repo(tmp_path)
    base = run(repo,"git","rev-parse","HEAD")
    (repo/".env").write_text("TOKEN=super-secret\n")
    service = DevelopmentRecoveryCheckpointService(repo)
    with pytest.raises(CheckpointBlocked) as exc:
        service.persist(
            ledger=ledger(repo,base), mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
            canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
            recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
            runtime_namespace="rt1", agent_execution_identity="agent1", authorization_id="auth1",
            included_paths=["app","tests",".env"], excluded_paths=[],
        )
    assert exc.value.state == "BLOCKED_SECRET_RISK"
    assert exc.value.blocked_path == ".env"


def test_resume_detects_canonical_movement_and_side_effect_unknown(tmp_path: Path):
    repo,_ = init_repo(tmp_path)
    base = run(repo,"git","rev-parse","HEAD")
    service = DevelopmentRecoveryCheckpointService(repo)
    cp = service.persist(
        ledger=ledger(repo,base), mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt1", agent_execution_identity="agent1", authorization_id="auth1",
        included_paths=["app","tests"], excluded_paths=[],
    )
    ready = service.resume("recovery/dev/m1", canonical_branch="work/gate6f-analytics-learning")
    assert ready["outcome"] == "RESUME_READY"
    assert ready["checkpoint"]["checkpoint_id"] == cp["checkpoint_id"]

    (repo/"app"/"other.py").write_text("X=1\n")
    run(repo,"git","add","app/other.py"); run(repo,"git","commit","-m","move")
    run(repo,"git","push","origin","HEAD:work/gate6f-analytics-learning")
    moved = service.resume("recovery/dev/m1", canonical_branch="work/gate6f-analytics-learning")
    assert moved["outcome"] == "RECONCILIATION_REQUIRED"


def test_network_loss_after_verified_baseline_creates_local_degraded_ref_and_upgrades_later(tmp_path: Path):
    repo, remote = init_repo(tmp_path)
    base = run(repo, "git", "rev-parse", "HEAD")
    service = DevelopmentRecoveryCheckpointService(repo)
    first = service.persist(
        ledger=ledger(repo, base),
        mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt1", agent_execution_identity="agent1", authorization_id="auth1",
        included_paths=["app", "tests"], excluded_paths=[],
    )
    prior = first["recovery_commit_sha"]

    (repo / "app" / "base.py").write_text("BASE = 77\n")
    next_ledger = ledger(repo, base, seq=1)
    next_ledger["latest_verified_checkpoint_id"] = first["checkpoint_id"]
    next_ledger["latest_verified_checkpoint_sha"] = prior
    next_ledger["current_step"] = "offline-work"

    run(repo, "git", "remote", "set-url", "origin", str(tmp_path / "offline.git"))
    degraded = DevelopmentRecoveryCheckpointService(repo).persist(
        ledger=next_ledger,
        mission_id="m1", task_id="t2", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt1", agent_execution_identity="agent1", authorization_id="auth2",
        included_paths=["app", "tests"], excluded_paths=[],
        expected_previous_remote_oid=prior,
    )
    assert degraded["development_state"] == "LOCAL_DEGRADED"
    assert degraded["durability_mode"] == "LOCAL_DEGRADED"
    assert degraded["remote_durability"] == "FAIL"
    assert degraded["remote_readback_status"] == "FAILED"
    local_ref = degraded["local_recovery_ref"]
    assert local_ref.startswith("refs/br-no-gta-recovery-local/")
    assert run(repo, "git", "rev-parse", local_ref) == degraded["local_recovery_commit_sha"]
    assert run(repo, "git", "show", f"{local_ref}:app/base.py") == "BASE = 77"

    remote_canonical = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/work/gate6f-analytics-learning"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert remote_canonical == base
    remote_recovery = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/recovery/dev/m1"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert remote_recovery == prior

    run(repo, "git", "remote", "set-url", "origin", str(remote))
    upgraded = DevelopmentRecoveryCheckpointService(repo).persist(
        ledger=next_ledger,
        mission_id="m1", task_id="t2", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt1", agent_execution_identity="agent1", authorization_id="auth2",
        included_paths=["app", "tests"], excluded_paths=[],
        expected_previous_remote_oid=prior,
    )
    assert upgraded["development_state"] == "DURABLE"
    assert upgraded["remote_readback_status"] == "VERIFIED"
    assert upgraded["recovery_commit_sha"] != prior
