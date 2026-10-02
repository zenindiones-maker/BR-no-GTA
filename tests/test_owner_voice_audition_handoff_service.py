from __future__ import annotations

import json
import os
from pathlib import Path
import wave

import pytest

from app.services.owner_voice_audition_handoff_service import (
    HANDOFF_SCHEMA,
    build_run_scoped_workspace,
    commit_audition_handoff,
    generation_parameter_digest,
    verify_audition_handoff,
)


def _wav(path: Path, *, seconds: float, sample_rate: int = 16000, sample_value: int = 321) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * sample_rate)
    payload = int(sample_value).to_bytes(2, "little", signed=True) * frames
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(payload)
    return path.read_bytes()


def _candidate(label: str, path: Path, cfg: float) -> dict:
    return {
        "candidate_id": f"candidate-{label}",
        "label": label,
        "path": str(path),
        "voice_identity_id": "BR_OWNER_V1",
        "model_id": "ResembleAI/Chatterbox-Multilingual-pt-br",
        "model_revision": "b3952f18bc2eaa72b9bd7c17d2c4653bcad4770d",
        "reference_sha256": "a" * 64,
        "generation_parameters": {
            "cfg_weight": cfg,
            "temperature": 0.8,
            "exaggeration": 0.5,
            "seed": 424242,
        },
    }


def _three(workspace: Path) -> list[dict]:
    rows=[]
    for label,cfg in zip("ABC",(0.3,0.5,0.7)):
        path=workspace/f"{label}.wav"
        _wav(path,seconds=1.0+cfg)
        rows.append(_candidate(label,path,cfg))
    return rows


def test_run_scoped_workspace_is_exactly_under_runner_temp(tmp_path):
    workspace=build_run_scoped_workspace(
        runner_temp=tmp_path,
        github_run_id="36999999999",
        github_run_attempt="2",
    )
    assert workspace == (tmp_path/"br-owner-voice"/"36999999999"/"2").resolve()
    assert workspace.is_dir()
    assert workspace.parent.parent.parent == tmp_path.resolve()


def test_generation_parameter_digest_is_stable_and_sensitive():
    a=generation_parameter_digest({"cfg_weight":0.3,"temperature":0.8})
    b=generation_parameter_digest({"temperature":0.8,"cfg_weight":0.3})
    c=generation_parameter_digest({"cfg_weight":0.5,"temperature":0.8})
    assert a==b
    assert a!=c
    assert len(a)==64


def test_real_producer_consumer_handoff_verifies_exact_bytes_hashes_and_paths(tmp_path):
    workspace=build_run_scoped_workspace(
        runner_temp=tmp_path,github_run_id="101",github_run_attempt="1"
    )
    original_bytes={label:_wav(workspace/f"{label}.wav",seconds=1.0+idx*0.1)
                    for idx,label in enumerate("ABC")}
    candidates=[_candidate(label,workspace/f"{label}.wav",cfg)
                for label,cfg in zip("ABC",(0.3,0.5,0.7))]

    manifest_path=commit_audition_handoff(
        workspace=workspace,
        candidates=candidates,
        pack_id="BR_OWNER_V1_AUDITION_TEST",
    )
    assert manifest_path == workspace/"audition-manifest.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"]==HANDOFF_SCHEMA
    assert manifest["pack_id"]=="BR_OWNER_V1_AUDITION_TEST"
    assert manifest["voice_identity_id"]=="BR_OWNER_V1"
    assert manifest["workspace"]==str(workspace)
    assert [c["label"] for c in manifest["candidates"]]==["A","B","C"]

    verified=verify_audition_handoff(
        manifest_path,
        expected_pack_id="BR_OWNER_V1_AUDITION_TEST",
        expected_workspace=workspace,
    )
    assert verified["manifest_digest"]==manifest["manifest_digest"]
    for candidate in verified["candidates"]:
        label=candidate["label"]
        path=Path(candidate["private_runtime_path"])
        assert path == workspace/f"{label}.wav"
        assert path.read_bytes()==original_bytes[label]
        assert candidate["size_bytes"]==len(original_bytes[label])
        assert candidate["sha256"]
        assert candidate["duration_seconds"]>0
        assert candidate["voice_identity_id"]=="BR_OWNER_V1"
        assert candidate["generation_parameter_digest"]==generation_parameter_digest(
            next(x["generation_parameters"] for x in candidates if x["label"]==label)
        )


def test_consumer_rejects_hash_mismatch_without_path_reconstruction(tmp_path):
    workspace=build_run_scoped_workspace(runner_temp=tmp_path,github_run_id="102",github_run_attempt="1")
    rows=_three(workspace)
    manifest=commit_audition_handoff(workspace=workspace,candidates=rows,pack_id="pack-hash")
    (workspace/"B.wav").write_bytes((workspace/"B.wav").read_bytes()+b"tamper")
    with pytest.raises(ValueError,match="HANDOFF_SHA256_MISMATCH:B"):
        verify_audition_handoff(manifest,expected_pack_id="pack-hash",expected_workspace=workspace)


def test_consumer_rejects_partial_candidate_set(tmp_path):
    workspace=build_run_scoped_workspace(runner_temp=tmp_path,github_run_id="103",github_run_attempt="1")
    rows=_three(workspace)[:2]
    with pytest.raises(ValueError,match="HANDOFF_EXPECTS_EXACTLY_A_B_C"):
        commit_audition_handoff(workspace=workspace,candidates=rows,pack_id="pack-partial")
    assert not (workspace/"audition-manifest.json").exists()


@pytest.mark.parametrize(
    ("crash_stage","final_manifest_expected"),
    [
        ("after_wavs_before_manifest_commit",False),
        ("during_temp_manifest_write",False),
        ("after_atomic_manifest_commit",True),
        ("before_consumer",True),
    ],
)
def test_crash_boundaries_never_publish_partial_manifest(tmp_path,crash_stage,final_manifest_expected):
    workspace=build_run_scoped_workspace(
        runner_temp=tmp_path,github_run_id=f"crash-{crash_stage}",github_run_attempt="1"
    )
    rows=_three(workspace)

    def fault(stage: str) -> None:
        if stage==crash_stage:
            raise RuntimeError(f"CRASH:{stage}")

    with pytest.raises(RuntimeError,match="CRASH:"):
        commit_audition_handoff(
            workspace=workspace,candidates=rows,pack_id="pack-crash",fault_injector=fault
        )

    final=workspace/"audition-manifest.json"
    assert final.exists() is final_manifest_expected
    if final_manifest_expected:
        verify_audition_handoff(final,expected_pack_id="pack-crash",expected_workspace=workspace)
    else:
        with pytest.raises(FileNotFoundError):
            verify_audition_handoff(final,expected_pack_id="pack-crash",expected_workspace=workspace)


def test_crash_before_wav_completion_has_no_manifest(tmp_path):
    workspace=build_run_scoped_workspace(
        runner_temp=tmp_path,github_run_id="before-wav",github_run_attempt="1"
    )
    _wav(workspace/"A.wav",seconds=1.0)
    rows=[
        _candidate("A",workspace/"A.wav",0.3),
        _candidate("B",workspace/"B.wav",0.5),
        _candidate("C",workspace/"C.wav",0.7),
    ]
    with pytest.raises(ValueError,match="HANDOFF_CANDIDATE_FILE_MISSING:B"):
        commit_audition_handoff(workspace=workspace,candidates=rows,pack_id="pack-before-wav")
    assert not (workspace/"audition-manifest.json").exists()


def test_manifest_temp_file_never_counts_as_committed_handoff(tmp_path):
    workspace=build_run_scoped_workspace(
        runner_temp=tmp_path,github_run_id="temp-only",github_run_attempt="1"
    )
    (workspace/".audition-manifest.json.tmp").write_text('{"partial":',encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        verify_audition_handoff(
            workspace/"audition-manifest.json",
            expected_pack_id="x",
            expected_workspace=workspace,
        )
