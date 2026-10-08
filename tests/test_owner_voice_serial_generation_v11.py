from __future__ import annotations

import hashlib
import json
import stat
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.owner_voice_serial_generation_v11 import generate_one_private_audition


def _input():
    return {
        "segment_texts":["Booooa meu povo", "vaicy siti", "E BR não dorme em Vice City"],
        "segment_languages":["Portuguese"]*3,
        "segment_prompts":[object(),object(),object()],
    }


def _run(tmp_path, generate, heartbeat=None, plan=None):
    return generate_one_private_audition(
        generate=generate,heartbeat=heartbeat or (lambda fn,**kwargs:fn(**kwargs)),
        workspace=tmp_path,**(plan or _input())
    )


def test_three_owner_segments_real_private_wav_checkpoints_and_single_candidate(tmp_path,capsys):
    calls=[]
    def generate(**kwargs):
        calls.append(kwargs)
        return [np.ones(2400,dtype=np.float32)*0.15],24000
    wavs,rate,elapsed,receipts=_run(tmp_path,generate)
    assert len(wavs)==len(receipts)==3 and rate==24000
    assert len(calls)==3
    assert all(len(c["text"])==len(c["language"])==len(c["voice_clone_prompt"])==1 for c in calls)
    assert [c["text"][0] for c in calls]==_input()["segment_texts"]
    assert all(c["non_streaming_mode"] is True for c in calls)
    assert all(rec["owner_voice_identity"]=="BR_OWNER_V1" for rec in receipts)
    assert all(rec["human_approved"] is False for rec in receipts)
    assert all(rec["external_persistence"]=="NOT_ATTEMPTED" for rec in receipts)
    for i in range(1,4):
        path=tmp_path/f"private-qwen-segment-{i:02d}.wav"
        json_path=tmp_path/f"private-qwen-segment-{i:02d}.json"
        assert stat.S_IMODE(path.stat().st_mode)==0o600
        assert stat.S_IMODE(json_path.stat().st_mode)==0o600
        with wave.open(str(path),"rb") as wav:
            assert wav.getnchannels()==1
            assert wav.getframerate()==24000
            assert wav.getnframes()==2400
        payload=json.loads(json_path.read_text())
        assert payload["wav_sha256"]==hashlib.sha256(path.read_bytes()).hexdigest()
        assert payload["text_sha256"]==hashlib.sha256(_input()["segment_texts"][i-1].encode()).hexdigest()
    logs=capsys.readouterr().out
    assert "OWNER_QWEN_SINGLE_CANDIDATE_SEGMENTED=PASS" in logs
    assert "vaicy siti" not in logs
    assert "Booooa meu povo" not in logs


def test_candidate_checkpoint_cannot_be_reused_in_second_attempt(tmp_path):
    generator=lambda **_kw:([np.ones(2400,dtype=np.float32)*0.2],24000)
    _run(tmp_path,generator)
    with pytest.raises(RuntimeError,match="REUSE_OF_EXISTING_CHECKPOINT"):
        _run(tmp_path,generator)


def test_sample_rate_drift_fails_closed_without_creating_second_checkpoint(tmp_path):
    index=0
    def generator(**kwargs):
        nonlocal index
        index+=1
        return [np.ones(2400,dtype=np.float32)*0.2],24000 if index==1 else 22050
    with pytest.raises(RuntimeError,match="SAMPLE_RATE_DRIFT"):
        _run(tmp_path,generator)
    assert (tmp_path/"private-qwen-segment-01.wav").exists()
    assert not (tmp_path/"private-qwen-segment-02.wav").exists()


@pytest.mark.parametrize("samples",[
    np.zeros(0,dtype=np.float32),
    np.array([float("nan")]*3000,dtype=np.float32),
    np.array([float("inf")]*3000,dtype=np.float32),
])
def test_corrupt_or_empty_audio_cannot_be_checkpointed(tmp_path,samples):
    with pytest.raises(RuntimeError,match="GENERATED_AUDIO_INVALID"):
        _run(tmp_path,lambda **_kw:([samples],24000))
    assert not list(tmp_path.glob("private-qwen-segment-*.wav"))


def test_wrong_plan_and_missing_or_dangerous_workspace_rejected(tmp_path):
    bad=_input()
    bad["segment_prompts"]=[None,None,None]
    with pytest.raises(RuntimeError,match="SEGMENT_PLAN_INVALID"):
        _run(tmp_path,lambda **kw:None,plan=bad)
    symlink=tmp_path/"alias"
    symlink.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(RuntimeError,match="PRIVATE_WORKSPACE_INVALID"):
        generate_one_private_audition(
            generate=lambda **kw:None,heartbeat=lambda fn,**kw:None,
            workspace=symlink,**_input()
        )


def test_generation_exception_never_prints_success_or_creates_unapproved_audio(tmp_path,capsys):
    def generate(**kwargs):
        raise RuntimeError("QWEN_GENERATION_ABORTED")
    with pytest.raises(RuntimeError,match="QWEN_GENERATION_ABORTED"):
        _run(tmp_path,generate)
    assert "OWNER_QWEN_SINGLE_CANDIDATE_SEGMENTED=PASS" not in capsys.readouterr().out
    assert not list(tmp_path.glob("private-qwen-segment-*.wav"))
