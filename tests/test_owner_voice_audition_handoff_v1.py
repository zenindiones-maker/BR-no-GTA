from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.owner_voice_audition_handoff_service import (
    HandoffCrash,
    commit_audition_handoff,
    consume_audition_handoff,
    run_scoped_workspace,
)


def _write_dummy(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(payload)


def test_run_scoped_workspace_is_exactly_runner_temp_run_id_attempt(tmp_path):
    root=run_scoped_workspace(tmp_path,github_run_id="123",github_run_attempt="4")
    assert root==(tmp_path/"br-owner-voice"/"123"/"4").resolve()
    assert root.is_dir()


def test_real_producer_consumer_contract_uses_exact_manifest_and_hashes(tmp_path):
    root=run_scoped_workspace(tmp_path,github_run_id="10",github_run_attempt="2")
    sources=[]
    for label,payload in [("A",b"RIFF-AUDIO-A"),("B",b"RIFF-AUDIO-B"),("C",b"RIFF-AUDIO-C")]:
        src=root/f"{label}.wav"
        _write_dummy(src,payload)
        sources.append({
            "candidate_id":label,
            "path":str(src),
            "duration_seconds":61.5,
            "voice_identity_id":"BR_OWNER_V1",
            "model_id":"ResembleAI/Chatterbox-Multilingual-pt-br",
            "model_revision":"rev-1",
            "reference_sha256":"a"*64,
            "generation_parameters":{"cfg_weight":{"A":0.3,"B":0.5,"C":0.7}[label],"seed":424242},
        })
    manifest=commit_audition_handoff(
        workspace=root,pack_id="pack-123",candidates=sources
    )
    assert manifest.name=="audition-manifest.json"
    payload=json.loads(manifest.read_text())
    assert payload["schema_version"]=="OwnerVoiceAuditionHandoff/v1"
    assert {c["candidate_id"] for c in payload["candidates"]}=={"A","B","C"}
    accepted=consume_audition_handoff(manifest,expected_pack_id="pack-123")
    assert [Path(x["runtime_path"]).read_bytes() for x in accepted["candidates"]]==[
        b"RIFF-AUDIO-A",b"RIFF-AUDIO-B",b"RIFF-AUDIO-C"
    ]
    assert accepted["manifest_path"]==str(manifest.resolve())


@pytest.mark.parametrize("crash_point",[
    "before_wav_completion",
    "after_wavs_before_manifest_commit",
    "during_temporary_manifest_write",
])
def test_partial_handoff_is_never_accepted(tmp_path,crash_point):
    root=run_scoped_workspace(tmp_path,github_run_id="11",github_run_attempt="1")
    rows=[]
    for label in ("A","B","C"):
        p=root/f"{label}.wav"
        _write_dummy(p,("audio-"+label).encode())
        rows.append({
            "candidate_id":label,"path":str(p),"duration_seconds":50,
            "voice_identity_id":"BR_OWNER_V1","model_id":"model","model_revision":"rev",
            "reference_sha256":"b"*64,"generation_parameters":{"seed":1},
        })
    with pytest.raises(HandoffCrash):
        commit_audition_handoff(
            workspace=root,pack_id="pack-crash",candidates=rows,crash_at=crash_point
        )
    assert not (root/"audition-manifest.json").exists()
    with pytest.raises((FileNotFoundError,ValueError)):
        consume_audition_handoff(root/"audition-manifest.json",expected_pack_id="pack-crash")


def test_crash_after_atomic_manifest_commit_is_consumer_safe(tmp_path):
    root=run_scoped_workspace(tmp_path,github_run_id="12",github_run_attempt="1")
    rows=[]
    for label in ("A","B","C"):
        p=root/f"{label}.wav"; _write_dummy(p,("audio-"+label).encode())
        rows.append({
            "candidate_id":label,"path":str(p),"duration_seconds":50,
            "voice_identity_id":"BR_OWNER_V1","model_id":"model","model_revision":"rev",
            "reference_sha256":"c"*64,"generation_parameters":{"seed":1},
        })
    with pytest.raises(HandoffCrash):
        commit_audition_handoff(
            workspace=root,pack_id="pack-atomic",candidates=rows,crash_at="after_atomic_manifest_commit"
        )
    manifest=root/"audition-manifest.json"
    accepted=consume_audition_handoff(manifest,expected_pack_id="pack-atomic")
    assert len(accepted["candidates"])==3


def test_consumer_rejects_tampered_candidate_hash(tmp_path):
    root=run_scoped_workspace(tmp_path,github_run_id="13",github_run_attempt="1")
    rows=[]
    for label in ("A","B","C"):
        p=root/f"{label}.wav"; _write_dummy(p,("audio-"+label).encode())
        rows.append({
            "candidate_id":label,"path":str(p),"duration_seconds":50,
            "voice_identity_id":"BR_OWNER_V1","model_id":"model","model_revision":"rev",
            "reference_sha256":"d"*64,"generation_parameters":{"seed":1},
        })
    manifest=commit_audition_handoff(workspace=root,pack_id="pack-hash",candidates=rows)
    (root/"B.wav").write_bytes(b"changed")
    with pytest.raises(ValueError,match="HANDOFF_SHA256_MISMATCH:B"):
        consume_audition_handoff(manifest,expected_pack_id="pack-hash")
