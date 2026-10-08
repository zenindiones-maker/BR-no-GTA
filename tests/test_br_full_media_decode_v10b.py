from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import br_full_media_decode_v10b as full
from app.services.br_production_forensic_qa_v10 import SCHEMA as QA_SCHEMA


def _source(tmp_path):
    path=tmp_path/"owned.mp4"
    path.write_bytes(b"owner-standalone-fixture"*120)
    return path


def _sampled(path,*,profile="synthetic_ci_canary",length=3.0):
    from app.services.br_production_forensic_qa_v10 import _sha256
    row={
        "schema_version":QA_SCHEMA,
        "status":"TECHNICAL_SAMPLED_QA_PASS",
        "profile":profile,
        "source_sha256":_sha256(path),
        "metadata":{"duration_seconds":length},
        "publish_authorized":False,
        "human_review_approved":False,
        "voice_identity_verified":False,
    }
    row["receipt_sha256"]=hashlib.sha256(json.dumps(
        row,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()
    return row


def _progress(frames=90,seconds=3.0,done=True,exitcode=0):
    return SimpleNamespace(
        stdout=f"frame={frames}\nout_time_us={round(seconds*1000000)}\n"+(
            "progress=end\n" if done else "progress=continue\n"
        ),
        stderr="",returncode=exitcode,
    )


def test_canary_full_decode_passes_without_claiming_real_master(tmp_path,monkeypatch):
    path=_source(tmp_path)
    calls=[]
    monkeypatch.setattr(full,"_runner",lambda args,timeout:(calls.append(args) or _progress()))
    result=full.verify_full_decode(path,_sampled(path),timeout_seconds=180)
    assert result["status"]=="FULL_SYNTHETIC_CANARY_DECODE_PASS"
    assert result["entire_video_decoder_completed"] is True
    assert result["entire_audio_decoder_completed"] is True
    assert result["publish_authorized"] is False
    assert result["audio_identity_certified"] is False
    assert result["can_authorize_render"] is False
    assert len(calls)==2
    assert "-map" in calls[0] and "0:v:0" in calls[0]
    assert "-map" in calls[1] and "0:a:0" in calls[1]
    assert "-c:v" in calls[0] and "rawvideo" in calls[0]
    assert result["evidence_sha256"]


@pytest.mark.parametrize("params",[
    {"frames":2,"seconds":3.0},
    {"frames":90,"seconds":0.3},
    {"frames":90,"seconds":3.0,"done":False},
    {"frames":90,"seconds":3.0,"exitcode":1},
])
def test_partial_or_error_decode_rejected(tmp_path,monkeypatch,params):
    path=_source(tmp_path)
    monkeypatch.setattr(full,"_runner",lambda *a,**k:_progress(**params))
    result=full.verify_full_decode(path,_sampled(path))
    assert result["status"]=="FULL_DECODE_BLOCKED"
    assert result["entire_video_decoder_completed"] is False
    assert result["publish_authorized"] is False


def test_tampered_or_substituted_media_cannot_be_certified(tmp_path,monkeypatch):
    path=_source(tmp_path)
    source=_sampled(path)
    source["status"]="TECHNICAL_QA_FAIL"
    with pytest.raises(ValueError,match="RECEIPT_DRIFT"):
        full.verify_full_decode(path,source)
    source=_sampled(path)
    path.write_bytes(path.read_bytes()+b"tampered")
    with pytest.raises(ValueError,match="SOURCE_OR_RECEIPT_DRIFT"):
        full.verify_full_decode(path,source)


def test_20_minute_master_cannot_pass_3sec_fixture(tmp_path,monkeypatch):
    path=_source(tmp_path)
    with pytest.raises(ValueError,match="LONGFORM_LENGTH_INVALID"):
        full.verify_full_decode(path,_sampled(path,profile="br_no_gta_1080p_master"))



def test_full_video_cannot_hide_shortened_audio_track(tmp_path,monkeypatch):
    path=_source(tmp_path)
    counter=0
    def runner(*_args,**_kwargs):
        nonlocal counter
        counter+=1
        return _progress(seconds=3.0 if counter==1 else 0.8)
    monkeypatch.setattr(full,"_runner",runner)
    evidence=full.verify_full_decode(path,_sampled(path))
    assert evidence["status"]=="FULL_DECODE_BLOCKED"
    assert evidence["entire_video_decoder_completed"] is True
    assert evidence["entire_audio_decoder_completed"] is False
    assert evidence["checks"]["audio_time_at_least_98pct"] is False
    assert evidence["publish_authorized"] is False
