from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from app.services.development_recovery_checkpoint_service import DevelopmentRecoveryCheckpointService
from tests.test_development_recovery_checkpoint_service import init_repo, ledger, run


def test_restore_reconstructs_recovery_source_into_fresh_clean_workspace(tmp_path: Path):
    repo,remote=init_repo(tmp_path)
    base=run(repo,"git","rev-parse","HEAD")
    (repo/"app"/"base.py").write_text("BASE = 42\n")
    (repo/"tests"/"new_recovery_test.py").write_text("VALUE = 'recovered'\n")
    payload=ledger(repo,base)
    payload["current_step"]="continue-after-recovery"
    cp=DevelopmentRecoveryCheckpointService(repo).persist(
        ledger=payload, mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt", agent_execution_identity="a", authorization_id="auth",
        included_paths=["app","tests"], excluded_paths=[]
    )

    fresh=tmp_path/"fresh"
    subprocess.run(["git","clone",str(remote),str(fresh)],check=True,capture_output=True)
    run(fresh,"git","checkout","work/gate6f-analytics-learning")
    assert (fresh/"app"/"base.py").read_text()=="BASE = 1\n"
    assert not (fresh/"tests"/"new_recovery_test.py").exists()

    result=DevelopmentRecoveryCheckpointService(fresh).restore(
        "recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning"
    )
    assert result["outcome"]=="RESUME_READY"
    assert result["restored"] is True
    assert result["checkpoint"]["recovery_commit_sha"]==cp["recovery_commit_sha"]
    assert (fresh/"app"/"base.py").read_text()=="BASE = 42\n"
    assert (fresh/"tests"/"new_recovery_test.py").read_text()=="VALUE = 'recovered'\n"
    assert ".development-recovery" not in run(fresh,"git","status","--porcelain=v1","-uall")
    status=run(fresh,"git","status","--porcelain=v1","-uall")
    assert "app/base.py" in status
    assert "tests/new_recovery_test.py" in status


def test_restore_refuses_dirty_workspace(tmp_path: Path):
    repo,_=init_repo(tmp_path)
    base=run(repo,"git","rev-parse","HEAD")
    svc=DevelopmentRecoveryCheckpointService(repo)
    svc.persist(
        ledger=ledger(repo,base), mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt", agent_execution_identity="a", authorization_id="auth",
        included_paths=["app","tests"], excluded_paths=[]
    )
    (repo/"local-only.txt").write_text("dirty\n")
    result=svc.restore("recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning")
    assert result["outcome"]=="RECONCILIATION_REQUIRED"
    assert result["reason"]=="DIRTY_WORKSPACE"
