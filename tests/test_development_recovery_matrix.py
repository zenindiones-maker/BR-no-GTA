from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from app.services.development_recovery_checkpoint_service import (
    CheckpointBlocked,
    DevelopmentRecoveryCheckpointService,
)
from tests.test_development_recovery_checkpoint_service import init_repo, ledger, run


def persist(svc, repo, base, payload=None, **kw):
    return svc.persist(
        ledger=payload or ledger(repo,base), mission_id="m1", task_id=kw.pop("task_id","t1"),
        checkpoint_kind=kw.pop("checkpoint_kind","RECOVERY"),
        canonical_branch="work/gate6f-analytics-learning", canonical_base_sha=base,
        recovery_ref="recovery/dev/m1", workspace_id="w1", sprite_id="s1",
        runtime_namespace="rt", agent_execution_identity="a", authorization_id="auth",
        included_paths=kw.pop("included_paths",["app","tests"]), excluded_paths=kw.pop("excluded_paths",[]),
        **kw
    )


def test_ignored_unclassified_file_is_excluded(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD")
    (repo/".gitignore").write_text("scratch.bin\n")
    run(repo,"git","add",".gitignore"); run(repo,"git","commit","-m","ignore"); run(repo,"git","push","origin","HEAD:work/gate6f-analytics-learning")
    base=run(repo,"git","rev-parse","HEAD")
    (repo/"scratch.bin").write_text("not recoverable\n")
    cp=persist(DevelopmentRecoveryCheckpointService(repo),repo,base,included_paths=["app","tests","scratch.bin"])
    assert "scratch.bin" not in cp["included_paths"]
    tree=run(repo,"git","ls-tree","-r","--name-only",cp["recovery_commit_sha"])
    assert "scratch.bin" not in tree.splitlines()


def test_large_evidence_without_external_bytes_blocks_durable_checkpoint(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD")
    (repo/"logs").mkdir(); (repo/"logs"/"root.log").write_bytes(b"x"*4096)
    with pytest.raises(CheckpointBlocked) as exc:
        persist(DevelopmentRecoveryCheckpointService(repo),repo,base,included_paths=["app","tests","logs"])
    assert exc.value.state=="BLOCKED_UNDURABLE_MATERIAL"
    assert exc.value.blocked_path=="logs/root.log"


def test_checkpoint_sequence_is_monotonic(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD"); svc=DevelopmentRecoveryCheckpointService(repo)
    first=persist(svc,repo,base)
    (repo/"app"/"base.py").write_text("BASE=22\n")
    p=ledger(repo,base); p["checkpoint_sequence"]=1; p["current_step"]="later"
    second=persist(svc,repo,base,payload=p,task_id="t2",expected_previous_remote_oid=first["recovery_commit_sha"])
    assert second["checkpoint_sequence"]==first["checkpoint_sequence"]+1


def test_promotion_checkpoint_is_forbidden(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD")
    with pytest.raises(PermissionError):
        persist(DevelopmentRecoveryCheckpointService(repo),repo,base,checkpoint_kind="PROMOTION")


def test_recovery_history_never_enters_canonical_history(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD")
    cp=persist(DevelopmentRecoveryCheckpointService(repo),repo,base)
    canonical=run(repo,"git","ls-remote","origin","refs/heads/work/gate6f-analytics-learning").split()[0]
    assert canonical==base
    ancestors=run(repo,"git","rev-list",canonical).splitlines()
    assert cp["recovery_commit_sha"] not in ancestors


def _corrupt_remote(repo: Path, oid: str, path: str, content: bytes) -> str:
    run(repo,"git","config","user.email","test@example.invalid"); run(repo,"git","config","user.name","Test")
    env=dict(__import__("os").environ)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        env["GIT_INDEX_FILE"]=str(Path(td)/"index")
        run(repo,"git","read-tree",oid,env=env)
        blob=subprocess.run(["git","hash-object","-w","--stdin"],cwd=repo,input=content,capture_output=True,check=True).stdout.decode().strip()
        run(repo,"git","update-index","--add","--cacheinfo","100644",blob,path,env=env)
        tree=run(repo,"git","write-tree",env=env)
        cp=subprocess.run(["git","commit-tree",tree,"-p",oid],cwd=repo,input="corrupt\n",text=True,capture_output=True,check=True)
        bad=cp.stdout.strip()
    run(repo,"git","push","origin",f"{bad}:refs/heads/recovery/dev/m1")
    return bad


def test_corrupt_checkpoint_core_returns_explicit_corrupt(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD"); svc=DevelopmentRecoveryCheckpointService(repo)
    cp=persist(svc,repo,base)
    _corrupt_remote(repo,cp["recovery_commit_sha"],".development-recovery/m1/checkpoint-core.json",b"{broken")
    assert DevelopmentRecoveryCheckpointService(repo).resume("recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning")["outcome"]=="CHECKPOINT_CORRUPT"


def test_corrupt_progress_ledger_returns_explicit_corrupt(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD"); svc=DevelopmentRecoveryCheckpointService(repo)
    cp=persist(svc,repo,base)
    _corrupt_remote(repo,cp["recovery_commit_sha"],".development-recovery/m1/progress-ledger.json",b"{}")
    assert DevelopmentRecoveryCheckpointService(repo).resume("recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning")["outcome"]=="CHECKPOINT_CORRUPT"


def test_resume_rejects_wrong_expected_remote_sha_and_tree(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD"); svc=DevelopmentRecoveryCheckpointService(repo)
    cp=persist(svc,repo,base)
    stale=svc.resume(
        "recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning",
        expected_recovery_commit_sha="f"*40,
    )
    assert stale["outcome"]=="CHECKPOINT_STALE"
    corrupt=svc.resume(
        "recovery/dev/m1",canonical_branch="work/gate6f-analytics-learning",
        expected_recovery_commit_sha=cp["recovery_commit_sha"],
        expected_recovery_tree_sha="f"*40,
    )
    assert corrupt["outcome"]=="CHECKPOINT_CORRUPT"


def test_resume_wrong_canonical_branch_identity_is_stale(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD"); svc=DevelopmentRecoveryCheckpointService(repo)
    persist(svc,repo,base)
    # Create a second remote branch only to make lookup valid; identity must still fail closed.
    run(repo,"git","push","origin",f"{base}:refs/heads/other")
    result=svc.resume("recovery/dev/m1",canonical_branch="other")
    assert result["outcome"]=="CHECKPOINT_STALE"


def test_workspace_locator_and_digest_are_not_treated_as_durable_external_storage(tmp_path: Path):
    repo,_=init_repo(tmp_path); base=run(repo,"git","rev-parse","HEAD")
    (repo/"logs").mkdir(); (repo/"logs"/"trace.log").write_text("trace\n")
    with pytest.raises(CheckpointBlocked) as exc:
        persist(DevelopmentRecoveryCheckpointService(repo),repo,base,included_paths=["app","logs"])
    assert exc.value.state=="BLOCKED_UNDURABLE_MATERIAL"
    assert exc.value.blocked_path=="logs/trace.log"
    assert "verified durable external storage" in exc.value.reason
