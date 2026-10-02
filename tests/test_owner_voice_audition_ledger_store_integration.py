from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from app.services.harness_git_transaction_store import CasConflict
from app.services.owner_voice_audition_ledger_store import (
    ALLOWED_LEDGER_BRANCH,
    OwnerVoiceAuditionGitLedgerStore,
)


def _run(cwd: Path,*args: str)->str:
    cp=subprocess.run(args,cwd=cwd,text=True,capture_output=True,check=True)
    return cp.stdout.strip()


def test_real_local_git_store_is_fast_forward_cas_and_stale_writer_fails(tmp_path):
    bare=tmp_path/"remote.git"
    work=tmp_path/"work"
    subprocess.run(["git","init","--bare",str(bare)],check=True,capture_output=True)
    subprocess.run(["git","init",str(work)],check=True,capture_output=True)
    _run(work,"git","config","user.name","test")
    _run(work,"git","config","user.email","test@example.invalid")
    (work/"README").write_text("base\n")
    _run(work,"git","add","README")
    _run(work,"git","commit","-m","base")
    _run(work,"git","branch","-M",ALLOWED_LEDGER_BRANCH)
    _run(work,"git","remote","add","origin",str(bare))
    _run(work,"git","push","origin",f"HEAD:{ALLOWED_LEDGER_BRANCH}")
    base=_run(work,"git","rev-parse","HEAD")

    key=tmp_path/"unused-key"
    key.write_text("not-used-for-local-path\n")
    store=OwnerVoiceAuditionGitLedgerStore(
        repo_root=work,
        repository_ssh=str(bare),
        ssh_private_key_path=key,
    )
    snap=store.snapshot("mission-a")
    assert snap.head_sha==base
    assert snap.mission_head is None

    new=store.transact(
        mission_id="mission-a",
        expected_head_sha=base,
        expected_state_version=None,
        mission_head={"state_version":0,"value":"first"},
        immutable_objects={"missions/mission-a/events/v000000.json":{"event":"created"}},
    )
    assert new!=base
    read=store.snapshot("mission-a")
    assert read.head_sha==new
    assert read.mission_head=={"state_version":0,"value":"first"}

    with pytest.raises(CasConflict,match="CAS_CONFLICT"):
        store.transact(
            mission_id="mission-a",
            expected_head_sha=base,
            expected_state_version=None,
            mission_head={"state_version":0,"value":"stale"},
            immutable_objects={},
        )
