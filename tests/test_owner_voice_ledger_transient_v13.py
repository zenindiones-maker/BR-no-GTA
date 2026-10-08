from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.harness_git_transaction_store import CasConflict
from app.services.owner_voice_audition_ledger_store import (
    OwnerVoiceAuditionGitLedgerStore,ALLOWED_LEDGER_REF,
)


def _store(root):
    key=root/"key"
    key.write_text("synthetic")
    return OwnerVoiceAuditionGitLedgerStore(
        repo_root=root,repository_ssh=str(root/"bare.git"),ssh_private_key_path=key,
    )


def test_exact_transient_commit_refs_52_one_retry_same_candidate(tmp_path,monkeypatch):
    store=_store(tmp_path)
    old="1"*40
    new="2"*40
    points=iter([old,old,new])
    monkeypatch.setattr(store,"_remote_oid",lambda:next(points))
    calls=[]
    def fake_run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=52 if len(calls)==1 else 0,
            stderr="fatal error in commit_refs" if len(calls)==1 else "",
        )
    monkeypatch.setattr("app.services.owner_voice_audition_ledger_store.subprocess.run",fake_run)
    assert store._push_candidate_bounded(expected_head_sha=old,candidate=new)==new
    assert len(calls)==2
    assert calls[0]==calls[1]
    assert calls[0]==["git","push",store.repository_ssh,f"{new}:{ALLOWED_LEDGER_REF}"]
    assert "--force" not in " ".join(calls[0])


def test_transient_twice_blocks_without_infinite_retry(tmp_path,monkeypatch):
    store=_store(tmp_path)
    old="1"*40
    new="2"*40
    points=iter([old,old,old])
    monkeypatch.setattr(store,"_remote_oid",lambda:next(points))
    calls=[]
    def reject(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=52,stderr="fatal error in commit_refs")
    monkeypatch.setattr("app.services.owner_voice_audition_ledger_store.subprocess.run",reject)
    with pytest.raises(RuntimeError,match="TRANSIENT_COMMIT_REFS_EXHAUSTED"):
        store._push_candidate_bounded(expected_head_sha=old,candidate=new)
    assert len(calls)==2


def test_remote_moved_is_cas_conflict_never_replayed(tmp_path,monkeypatch):
    store=_store(tmp_path)
    old="1"*40
    new="2"*40
    changed="3"*40
    points=iter([old,changed])
    monkeypatch.setattr(store,"_remote_oid",lambda:next(points))
    count={"value":0}
    def reject(*a,**kw):
        count["value"]+=1
        return SimpleNamespace(returncode=52,stderr="fatal error in commit_refs")
    monkeypatch.setattr("app.services.owner_voice_audition_ledger_store.subprocess.run",reject)
    with pytest.raises(CasConflict,match="REMOTE_MOVED"):
        store._push_candidate_bounded(expected_head_sha=old,candidate=new)
    assert count["value"]==1


def test_unrelated_push_failure_does_not_trigger_retry(tmp_path,monkeypatch):
    store=_store(tmp_path)
    old="1"*40
    new="2"*40
    points=iter([old,old])
    monkeypatch.setattr(store,"_remote_oid",lambda:next(points))
    count={"value":0}
    def reject(*a,**kw):
        count["value"]+=1
        return SimpleNamespace(returncode=1,stderr="protected branch rejected")
    monkeypatch.setattr("app.services.owner_voice_audition_ledger_store.subprocess.run",reject)
    with pytest.raises(RuntimeError,match="FAST_FORWARD_PUSH_REJECTED"):
        store._push_candidate_bounded(expected_head_sha=old,candidate=new)
    assert count["value"]==1


def test_unreadable_prestate_prevents_any_write(tmp_path,monkeypatch):
    store=_store(tmp_path)
    monkeypatch.setattr(store,"_remote_oid",lambda:"b"*40)
    def forbidden(*a,**kwargs):
        raise AssertionError("push must not run")
    monkeypatch.setattr("app.services.owner_voice_audition_ledger_store.subprocess.run",forbidden)
    with pytest.raises(CasConflict,match="EXPECTED_OLD_OID"):
        store._push_candidate_bounded(expected_head_sha="a"*40,candidate="c"*40)
