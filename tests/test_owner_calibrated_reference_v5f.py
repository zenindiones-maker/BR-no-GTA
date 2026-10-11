"""v5f (owner-authorized 11/10/2026): segment-vs-reference uses the embedding of the
exact Qwen ref_audio (trimmed window); reference floor = p10 of owner 5-7 s windows
vs that same embedding (binding). Whole-audio 0.868594 unchanged."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.services.owner_voice_speaker_identity_service import (
    PROFILE_SCHEMA,
    calibrate_segment_identity_threshold,
    evaluate_language_matched_segment_identity_gate,
)

SRC=Path("scripts/owner_voice_single_human_clone.py").read_text()


def _emb(c):
    return [c,math.sqrt(max(0.0,1-c*c))]


def test_calibration_includes_reference_p10_when_reference_windows_given():
    cent=[0.6+0.01*i for i in range(30)]
    ref=[0.5+0.01*i for i in range(30)]
    cal=calibrate_segment_identity_threshold(cent,window_seconds=5.5,window_similarities_to_reference=ref)
    assert cal["centroid_min_similarity"]==pytest.approx(0.6+0.01*2.9,abs=0.011)
    assert cal["reference_min_similarity"]==pytest.approx(0.5+0.01*2.9,abs=0.011)
    assert cal["reference_window_count"]==30


def test_calibrated_reference_floor_is_binding_in_gate():
    profile={"schema_version":PROFILE_SCHEMA,"centroid":[1.0,0.0],
             "clone_centroid_min_similarity":0.868594,"clone_reference_min_similarity":0.793141}
    cal={"calibration":"OWNER_DURATION_MATCHED_WINDOW_P10","centroid_min_similarity":0.68,
         "reference_min_similarity":0.70}
    seg=[{"position":1,"language":"pt","embedding":_emb(0.78),"reference_embedding":[1.0,0.0]}]
    out=evaluate_language_matched_segment_identity_gate(profile,segments=seg,segment_calibration=cal)
    assert out["segments"][0]["passed"] is True
    assert out["reference_min_similarity"]==0.70
    cal_low={**cal,"reference_min_similarity":0.80}
    out=evaluate_language_matched_segment_identity_gate(profile,segments=seg,segment_calibration=cal_low)
    assert out["segments"][0]["passed"] is False


def test_script_uses_exact_qwen_reference_embedding_for_segments():
    assert "qwen_reference_embedding=_embedding(classifier,qwen_reference16)" in SRC
    assert "canonical_embedding=qwen_reference_embedding," in SRC
    assert "OWNER_QWEN_REFERENCE_EMBEDDING_SOURCE=EXACT_QWEN_REF_AUDIO" in SRC
    assert "window_similarities_to_reference=reference_window_sims" in SRC
    # owner windows from the canonical clip itself are excluded (window was cut from it)
    assert "if rid not in reference_clip_ids" in SRC


def test_agents_md_documents_reference_calibration_authorization():
    text=Path("AGENTS.md").read_text()
    assert "OWNER_AUTHORIZED_20261011_SEGMENT_REFERENCE_P10_BINDING" in text
