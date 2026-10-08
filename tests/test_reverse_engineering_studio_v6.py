from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.services import reverse_engineering_studio_v6_service as studio
from app.services.reverse_engineering_media_service import ObservationError


def _sample(tmp_path: Path, name: str = "reference.wav"):
    path=tmp_path/name
    path.write_bytes(b"owned-test-material")
    return path


def _probe():
    return {"duration_seconds":3.0,"streams":[{"codec_type":"audio","sample_rate":"16000","channels":2}]}


def test_stems_measure_rms_stereo_cancellation_and_sum_clipping(tmp_path, monkeypatch):
    a,b=_sample(tmp_path,"drums.wav"),_sample(tmp_path,"music.wav")
    t=np.arange(32000)/16000
    s=np.sin(2*np.pi*440*t)*0.8
    first=np.stack([s,s],axis=1)
    second=np.stack([s,-s],axis=1)
    monkeypatch.setattr(studio,"probe_media",lambda _: _probe())
    monkeypatch.setattr(studio,"_f32_stereo",lambda p, seconds: first if p==a.resolve() else second)
    result=studio.analyze_stems([a,b],window_seconds=2)
    assert result["status"]=="MEASURED"
    assert result["source_count"]==2
    assert result["stems"][0]["stereo_correlation"]==1.0
    assert result["stems"][1]["stereo_correlation"]==-1.0
    assert result["stems"][1]["mono_compatibility_proxy"]==0
    assert result["unity_sum_exceeds_0dbfs"] is True
    assert result["reaper_project_created"] is False
    assert result["quality_approved"] is False
    assert len(result["evidence_sha256"])==64


def test_stems_reject_duplicate_missing_surround_and_long_analysis(tmp_path, monkeypatch):
    a=_sample(tmp_path)
    with pytest.raises(ObservationError,match="STUDIO_STEMS_COUNT_INVALID"):
        studio.analyze_stems([a])
    with pytest.raises(ObservationError,match="STUDIO_STEM_WINDOW_INVALID"):
        studio.analyze_stems([a,a],window_seconds=300)
    with pytest.raises(ObservationError,match="STUDIO_DUPLICATED_STEM"):
        studio.analyze_stems([a,a])
    monkeypatch.setattr(studio,"probe_media",lambda _: {
        "duration_seconds":3,"streams":[{"codec_type":"audio","channels":6}],
    })
    with pytest.raises(ObservationError,match="STUDIO_STEM_SURROUND_REQUIRES_SEPARATE_GATE"):
        studio.analyze_stems([a,_sample(tmp_path,"b.wav")])


def _alignment(tmp_path):
    doc={
        "language":"pt","model_id":"external-alignment-fixture-v1",
        "audio_sha256":"a"*64,"duration_seconds":2.0,
        "expected_tokens":["vaicy","siti"],
        "aligned_words":[
            {"word":"vaicy","start":0.0,"end":0.4,"score":0.98},
            {"word":"siti","start":0.5,"end":0.9,"score":0.96},
        ],
    }
    p=tmp_path/"alignment.json"
    p.write_text(json.dumps(doc),encoding="utf-8")
    return p,doc


def test_ptbr_alignment_is_not_proof_of_acoustic_pronunciation(tmp_path):
    p,doc=_alignment(tmp_path)
    r=studio.audit_external_word_alignment(p)
    assert r["counts"]["matched_text"]==2
    assert r["phoneme_pronunciation_verified"] is False
    assert r["speaker_identity_verified"] is False
    assert "vaicy siti" in r["vice_city_pronunciation"]
    assert "expected_tokens" not in json.dumps(r)
    doc["aligned_words"][1]["word"]="city"
    p.write_text(json.dumps(doc))
    s=studio.audit_external_word_alignment(p)
    assert s["counts"]["lexical_mismatch"]==1


def test_invalid_or_fabricated_alignment_is_blocked(tmp_path):
    p,data=_alignment(tmp_path)
    data["aligned_words"][1]["score"]=1.8
    p.write_text(json.dumps(data))
    with pytest.raises(ObservationError,match="STUDIO_ALIGNMENT_TIME_OR_SCORE_INVALID"):
        studio.audit_external_word_alignment(p)
    data["aligned_words"][1]["score"]=0.5
    data["aligned_words"][1]["start"]=-1
    p.write_text(json.dumps(data))
    with pytest.raises(ObservationError,match="STUDIO_ALIGNMENT_TIME_OR_SCORE_INVALID"):
        studio.audit_external_word_alignment(p)


def _timeline(tmp_path):
    manifest={
        "timeline_id":"original-br-v6",
        "fps_num":30000,"fps_den":1001,
        "tracks":[
            {"track_id":"V1","kind":"video","clips":[
                {"asset_id":"intro-original","at_frame":0,"source_in_frame":0,"duration_frames":30},
                {"asset_id":"part-01","at_frame":60,"source_in_frame":12,"duration_frames":45},
            ]},
            {"track_id":"A1","kind":"audio","clips":[
                {"asset_id":"original-bed","at_frame":0,"source_in_frame":0,"duration_frames":105},
            ]},
        ],
    }
    path=tmp_path/"timeline.json"
    path.write_text(json.dumps(manifest))
    return path,manifest


def test_real_otio_roundtrip_preserves_frames_and_track_gaps(tmp_path):
    p,plan=_timeline(tmp_path)
    r=studio.compile_original_timeline(p)
    assert r["status"]=="OTIO_SERIALIZED_AND_ROUNDTRIPPED"
    assert r["tracks"][0]["length_frames"]==105
    assert r["tracks"][0]["clip_count"]==2
    assert r["fps"]=={"numerator":30000,"denominator":1001}
    assert r["media_resolved"] is False and r["rendered"] is False
    assert r["publication_authorized"] is False


def test_otio_blocks_overlap_proprietary_urls_and_invalid_rates(tmp_path):
    p,data=_timeline(tmp_path)
    data["tracks"][0]["clips"][1]["at_frame"]=20
    p.write_text(json.dumps(data))
    with pytest.raises(ObservationError,match="STUDIO_TIMELINE_CLIP_RANGE_INVALID"):
        studio.compile_original_timeline(p)
    data["tracks"][0]["clips"][1]["at_frame"]=60
    data["tracks"][0]["clips"][0]["asset_id"]="https://private.example/secret"
    p.write_text(json.dumps(data))
    with pytest.raises(ObservationError,match="STUDIO_TIMELINE_ASSET_INVALID"):
        studio.compile_original_timeline(p)


def test_motion_frame_count_and_shape_are_limited_before_decode(tmp_path):
    p=_sample(tmp_path,"clip.mp4")
    with pytest.raises(ObservationError,match="STUDIO_MOTION_FRAME_WINDOW_INVALID"):
        studio.analyze_animation_motion(p,max_frames=200)
