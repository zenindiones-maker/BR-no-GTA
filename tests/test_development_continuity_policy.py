from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.services.development_recovery_checkpoint_service import (
    CheckpointConflict,
    DevelopmentRecoveryCheckpointService,
)
from tests.test_development_recovery_checkpoint_service import init_repo, ledger, run


def test_concurrent_writer_fencing_is_fast_forward_only(tmp_path: Path):
    repo,_ = init_repo(tmp_path)
    base = run(repo,"git","rev-parse","HEAD")
    a = DevelopmentRecoveryCheckpointService(repo)
    first = a.persist(
        ledger=ledger(repo,base), mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt1", agent_execution_identity="a", authorization_id="auth",
        included_paths=["app","tests"], excluded_paths=[],
    )
    expected = first["recovery_commit_sha"]

    # Competing writer advances the same ref from the exact same predecessor.
    clone = tmp_path/"competing"
    subprocess.run(["git","clone",str(tmp_path/"remote.git"),str(clone)],check=True,capture_output=True)
    run(clone,"git","config","user.email","test@example.invalid")
    run(clone,"git","config","user.name","Other")
    run(clone,"git","checkout","--detach",expected)
    (clone/"competitor.txt").write_text("other\n")
    run(clone,"git","add","competitor.txt"); run(clone,"git","commit","-m","competitor")
    other = run(clone,"git","rev-parse","HEAD")
    run(clone,"git","push","origin",f"{other}:refs/heads/recovery/dev/m1")

    (repo/"app"/"base.py").write_text("BASE=3\n")
    newer = ledger(repo,base)
    newer["checkpoint_sequence"] = 1
    newer["current_step"] = "b2"
    with pytest.raises(CheckpointConflict):
        a.persist(
            ledger=newer, mission_id="m1", task_id="t2", checkpoint_kind="RECOVERY",
            canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
            recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
            runtime_namespace="rt1", agent_execution_identity="a", authorization_id="auth",
            included_paths=["app","tests"], excluded_paths=[],
            expected_previous_remote_oid=expected,
        )
    assert run(repo,"git","ls-remote","origin","refs/heads/recovery/dev/m1").split()[0] == other


def test_side_effect_unknown_requires_reconciliation(tmp_path: Path):
    repo,_ = init_repo(tmp_path)
    base=run(repo,"git","rev-parse","HEAD")
    payload=ledger(repo,base)
    payload["side_effects"]["unknown_requires_reconciliation"]=["youtube:publication:7"]
    svc=DevelopmentRecoveryCheckpointService(repo)
    svc.persist(
        ledger=payload, mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt1", agent_execution_identity="a", authorization_id="auth",
        included_paths=["app","tests"], excluded_paths=[],
    )
    resumed=svc.resume("recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning")
    assert resumed["outcome"]=="SIDE_EFFECT_RECONCILIATION_REQUIRED"
