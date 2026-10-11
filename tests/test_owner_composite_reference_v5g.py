"""v5g: 20-30 s composite Qwen reference from 2-3 VAD windows of DIFFERENT owner clips."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.owner_voice_reference_window_service import (
    candidate_reference_windows,
    choose_composite_windows,
)

SRC=Path("scripts/owner_voice_single_human_clone.py").read_text()


def test_windows_accept_custom_bounds_for_composite_parts():
    spans=[(0.2,4.0),(4.6,9.0),(9.5,13.0)]
    wins=candidate_reference_windows(spans,13.2,min_seconds=6.0,max_seconds=15.0)
    assert wins and all(6.0<=b-a<=15.0 for a,b in wins)


def _cands():
    return {
        "c1":[((0.0,12.0),0.95),((5.0,14.0),0.93)],
        "c2":[((1.0,11.0),0.94)],
        "c3":[((0.0,9.0),0.97)],
        "c4":[((0.0,14.0),0.89)],  # below 0.90 -> never used
    }


def test_composite_uses_distinct_clips_total_20_30_and_maximizes_composite_sim():
    seen=[]
    def comp_sim(parts):
        seen.append(parts)
        ids=tuple(sorted(p[0] for p in parts))
        return {("c1","c2"):0.95,("c1","c3"):0.96,("c2","c3"):0.94,("c1","c2","c3"):0.975}.get(ids,0.5)
    parts,sim=choose_composite_windows(_cands(),comp_sim,min_window_similarity=0.90,gap_seconds=0.2)
    ids=[p[0] for p in parts]
    assert len(set(ids))==len(ids) and 2<=len(ids)<=3
    assert "c4" not in ids
    total=sum(w[1]-w[0] for _c,w in parts)+0.2*(len(parts)-1)
    assert 20.0<=total<=30.0
    assert sim==pytest.approx(0.975) and sorted(ids)==["c1","c2","c3"]
    for combo in seen:
        assert len({c for c,_w in combo})==len(combo)
        t=sum(w[1]-w[0] for _c,w in combo)+0.2*(len(combo)-1)
        assert 20.0<=t<=30.0


def test_composite_unavailable_fails_closed():
    with pytest.raises(RuntimeError,match="OWNER_QWEN_COMPOSITE_NOT_AVAILABLE"):
        choose_composite_windows({"c1":[((0.0,12.0),0.95)]},lambda p:0.99,
                                 min_window_similarity=0.90,gap_seconds=0.2)


def test_script_builds_composite_and_measures_exact_composite_embedding():
    assert "choose_composite_windows(" in SRC
    assert "OWNER_IDENTITY_PROMPT_MODE=MULTI_CLIP_VAD_WINDOW_COMPOSITE" in SRC
    assert "OWNER_QWEN_COMPOSITE_PARTS=" in SRC
    assert "OWNER_QWEN_COMPOSITE_SIMILARITY_TO_CENTROID=" in SRC
    # ref_text = per-window ASR concatenated and validated against exact audio
    assert 'anchor_ref_text=" ".join(window_transcripts)' in SRC
    assert "validate_composite_total(" in SRC and "validate_qwen_reference(" in SRC
    assert "qwen_reference_embedding=_embedding(classifier,qwen_reference16)" in SRC
    # calibration windows exclude every clip used in the composite
    assert "if rid not in reference_clip_ids" in SRC
    assert "MULTI_CLIP_VAD_WINDOW_COMPOSITE_LOUDNORM_24K" in SRC
