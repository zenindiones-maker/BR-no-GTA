from __future__ import annotations

from pathlib import Path

import pytest

from app.services.development_continuity_policy_service import recovery_gc_state
from app.services.development_recovery_checkpoint_service import DevelopmentRecoveryCheckpointService
from tests.test_development_recovery_checkpoint_service import init_repo, ledger, run


class Crash(RuntimeError):
    pass


def test_gc_is_blocked_until_promotion_current_head_evidence_and_retention():
    assert recovery_gc_state(
        promoted=False,current_head_verified=False,evidence_resolvable=True,retention_elapsed=True
    ) == "ACTIVE"
    assert recovery_gc_state(
        promoted=True,current_head_verified=False,evidence_resolvable=True,retention_elapsed=True
    ) == "PROMOTED"
    assert recovery_gc_state(
        promoted=True,current_head_verified=True,evidence_resolvable=True,retention_elapsed=False
    ) == "RETENTION_WINDOW"
    assert recovery_gc_state(
        promoted=True,current_head_verified=True,evidence_resolvable=False,retention_elapsed=True
    ) == "RETENTION_WINDOW"
    assert recovery_gc_state(
        promoted=True,current_head_verified=True,evidence_resolvable=True,retention_elapsed=True
    ) == "GC_ELIGIBLE"


def test_crash_before_remote_write_keeps_previous_verified_checkpoint(tmp_path: Path):
    repo,_=init_repo(tmp_path)
    base=run(repo,"git","rev-parse","HEAD")
    first=DevelopmentRecoveryCheckpointService(repo).persist(
        ledger=ledger(repo,base), mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1", runtime_namespace="rt",
        agent_execution_identity="a", authorization_id="auth", included_paths=["app","tests"], excluded_paths=[]
    )
    prior=first["recovery_commit_sha"]
    (repo/"app"/"base.py").write_text("BASE=9\n")
    newer=ledger(repo,base); newer["checkpoint_sequence"]=1; newer["current_step"]="new"
    def fault(stage: str):
        if stage=="before_remote_write":
            raise Crash(stage)
    with pytest.raises(Crash):
        DevelopmentRecoveryCheckpointService(repo,fault_injector=fault).persist(
            ledger=newer, mission_id="m1", task_id="t2", checkpoint_kind="RECOVERY",
            canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
            recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1", runtime_namespace="rt",
            agent_execution_identity="a", authorization_id="auth", included_paths=["app","tests"], excluded_paths=[],
            expected_previous_remote_oid=prior,
        )
    assert run(repo,"git","ls-remote","origin","refs/heads/recovery/dev/m1").split()[0]==prior
    resumed=DevelopmentRecoveryCheckpointService(repo).resume("recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning")
    assert resumed["outcome"]=="RESUME_READY"
    assert resumed["checkpoint"]["recovery_commit_sha"]==prior


def test_crash_after_remote_write_before_readback_fresh_executor_accepts_new_checkpoint(tmp_path: Path):
    repo,_=init_repo(tmp_path)
    base=run(repo,"git","rev-parse","HEAD")
    first=DevelopmentRecoveryCheckpointService(repo).persist(
        ledger=ledger(repo,base), mission_id="m1", task_id="t1", checkpoint_kind="RECOVERY",
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1", runtime_namespace="rt",
        agent_execution_identity="a", authorization_id="auth", included_paths=["app","tests"], excluded_paths=[]
    )
    prior=first["recovery_commit_sha"]
    (repo/"app"/"base.py").write_text("BASE=10\n")
    newer=ledger(repo,base); newer["checkpoint_sequence"]=1; newer["current_step"]="new"
    def fault(stage: str):
        if stage=="after_remote_write_before_readback":
            raise Crash(stage)
    with pytest.raises(Crash):
        DevelopmentRecoveryCheckpointService(repo,fault_injector=fault).persist(
            ledger=newer, mission_id="m1", task_id="t2", checkpoint_kind="RECOVERY",
            canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
            recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1", runtime_namespace="rt",
            agent_execution_identity="a", authorization_id="auth", included_paths=["app","tests"], excluded_paths=[],
            expected_previous_remote_oid=prior,
        )
    advanced=run(repo,"git","ls-remote","origin","refs/heads/recovery/dev/m1").split()[0]
    assert advanced != prior
    resumed=DevelopmentRecoveryCheckpointService(repo).resume("recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning")
    assert resumed["outcome"]=="RESUME_READY"
    assert resumed["checkpoint"]["recovery_commit_sha"]==advanced
