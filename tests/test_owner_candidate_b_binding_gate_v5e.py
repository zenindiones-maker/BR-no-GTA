"""v5e: candidate B stability sampling, lineage label, binding duration-calibrated segment gate.

Owner authorization (Luiz, 11/10/2026, chat): per-segment identity gate uses the
p10 of his real 5-7 s voice windows vs centroid as BINDING; whole-audio
centroid gate 0.868594 unchanged (and binding, fail-closed).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import owner_voice_serial_generation_v11 as v11
from app.services.owner_voice_speaker_identity_service import (
    evaluate_language_matched_segment_identity_gate,
)

SRC=Path("scripts/owner_voice_single_human_clone.py").read_text()


def test_candidate_b_sampling_is_stability_profile():
    assert v11.CANDIDATE_B_SAMPLING=={
        "do_sample":True,"temperature":0.55,"top_p":0.85,"top_k":30,
        "repetition_penalty":1.1,
        "subtalker_dosample":True,"subtalker_temperature":0.55,
        "subtalker_top_p":0.85,"subtalker_top_k":30,
    }
    assert isinstance(v11.CANDIDATE_B_BASE_SEED,int)
    assert v11.sampling_for_candidate("B")==(v11.CANDIDATE_B_SAMPLING,v11.CANDIDATE_B_BASE_SEED)
    assert v11.sampling_for_candidate("A")==(v11.CANDIDATE_A_SAMPLING,v11.CANDIDATE_A_BASE_SEED)
    with pytest.raises(RuntimeError,match="OWNER_QWEN_SAMPLING_CANDIDATE_INVALID"):
        v11.sampling_for_candidate("C")


def test_script_selects_candidate_from_request_and_logs_it():
    assert 'sampling_for_candidate(' in SRC
    assert 'request_payload.get("sampling_candidate"' in SRC
    assert '"OWNER_QWEN_SAMPLING_CANDIDATE="' in SRC


def test_lineage_label_reflects_single_window_mode():
    assert "OWNER_SINGLE_CANONICAL_VAD_WINDOW_LOUDNORM_24K" in SRC
    assert 'qwen_reference_audio_lineage=("OWNER_TOP_CENTROID_COMPOSITE_LOUDNORM_24K" if use_composite' in SRC


def _profile():
    return {"schema_version":"BROwnerSpeakerProfile/v1","centroid":[1.0,0.0],
            "clone_centroid_min_similarity":0.868594,"clone_reference_min_similarity":0.793141}


def test_duration_calibrated_gate_also_requires_reference_floor():
    """Explains 2/18 in run 38148278499: PT segments need centroid>=p10 AND
    similarity to the owner reference >= clone_reference_min_similarity."""
    import math
    def emb(cos):
        return [cos,math.sqrt(1-cos*cos)]
    cal={"calibration":"OWNER_DURATION_MATCHED_WINDOW_P10","centroid_min_similarity":0.677693}
    out=evaluate_language_matched_segment_identity_gate(
        {**_profile(),"schema_version":__import__(
            "app.services.owner_voice_speaker_identity_service",fromlist=["PROFILE_SCHEMA"]).PROFILE_SCHEMA},
        segments=[{"position":1,"language":"pt","embedding":emb(0.78),"reference_embedding":[1.0,0.0]}],
        segment_calibration=cal)
    row=out["segments"][0]
    assert row["similarity_to_centroid"]>=0.677693
    assert row["passed"] is False  # reference floor 0.793141 unchanged


def test_binding_identity_gate_uses_calibrated_segments_and_whole_audio():
    assert "SHADOW_NOT_BINDING" not in SRC
    assert "OWNER_SEGMENT_DURATION_CALIBRATION_MODE=BINDING_OWNER_AUTHORIZED_20261011" in SRC
    assert 'identity_gate="PASS" if (binding_segment_identity["passed"] is True and global_identity["passed"] is True) else "FAIL"' in SRC
    # calibration unavailable must fail closed
    assert "binding_segment_identity={\"passed\":False" in SRC


def test_agents_md_documents_owner_authorization():
    text=Path("AGENTS.md").read_text()
    assert "OWNER_AUTHORIZED_20261011_SEGMENT_GATE_P10_BINDING" in text
    assert "0.868594" in text
