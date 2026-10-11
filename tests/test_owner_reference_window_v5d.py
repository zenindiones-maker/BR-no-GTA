"""v5d: Qwen ref_audio must be <=30 s and ref_text must be the ASR of exactly that audio."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.owner_voice_reference_window_service import (
    MAX_QWEN_REFERENCE_SECONDS,
    candidate_reference_windows,
    choose_reference_window,
    validate_composite_total,
    validate_qwen_reference,
)

# Speech spans (s) of a 36 s owner clip, silences between them.
SPANS=[(0.4,3.9),(4.5,9.8),(10.3,14.6),(15.2,21.0),(21.6,27.9),(28.5,35.7)]


def test_windows_cut_only_at_silence_and_stay_in_10_to_20s():
    wins=candidate_reference_windows(SPANS,36.014)
    assert wins
    starts={round(s-0.15,3) for s,_ in SPANS}|{0.0}
    for start,end in wins:
        assert 10.0<=end-start<=20.0
        # boundaries fall inside a silence gap (or clip edges), never mid-speech
        for s,e in SPANS:
            assert not (s<start<e) and not (s<end<e)


def test_no_window_when_speech_cannot_fit():
    assert candidate_reference_windows([(0.0,35.0)],36.0)==[]


def test_choose_window_by_identity_and_enforce_floor():
    wins=[(0.25,14.75),(4.35,21.3),(10.15,27.95)]
    sims={wins[0]:0.93,wins[1]:0.97,wins[2]:0.95}
    best,sim=choose_reference_window(wins,sims.__getitem__,min_similarity=0.90)
    assert best==wins[1] and sim==0.97
    with pytest.raises(RuntimeError,match="OWNER_REFERENCE_WINDOW_IDENTITY_BELOW_FLOOR"):
        choose_reference_window(wins,lambda w:0.85,min_similarity=0.90)


@pytest.mark.parametrize("seconds",[36.014,30.5])
def test_reference_over_30s_rejected(seconds):
    with pytest.raises(RuntimeError,match="OWNER_QWEN_REFERENCE_TOO_LONG"):
        validate_qwen_reference(duration_seconds=seconds,ref_text="Booooa meu povo",
                                asr_transcript="Booooa meu povo")
    assert MAX_QWEN_REFERENCE_SECONDS==30.0


def test_ref_text_must_match_asr_of_trimmed_audio():
    validate_qwen_reference(duration_seconds=15.0,ref_text="Booooa, meu povo!",
                            asr_transcript="booooa meu povo")
    with pytest.raises(RuntimeError,match="OWNER_QWEN_REF_TEXT_AUDIO_MISMATCH"):
        validate_qwen_reference(duration_seconds=15.0,
            ref_text="Booooa meu povo, aqui é BR no GTA 6 e hoje vamos falar de tudo",
            asr_transcript="Booooa meu povo")
    with pytest.raises(RuntimeError,match="OWNER_QWEN_REF_TEXT_AUDIO_MISMATCH"):
        validate_qwen_reference(duration_seconds=15.0,ref_text="",asr_transcript="")


def test_composite_total_must_be_20_to_30s():
    validate_composite_total([12.0,10.0],gap_seconds=0.2)
    for durs in ([9.0,9.0],[16.0,15.0]):
        with pytest.raises(RuntimeError,match="OWNER_QWEN_COMPOSITE_DURATION_OUT_OF_RANGE"):
            validate_composite_total(durs,gap_seconds=0.2)


def test_clone_script_enforces_reference_bound_before_prompt_build():
    src=Path("scripts/owner_voice_single_human_clone.py").read_text()
    assert "validate_qwen_reference(" in src
    assert "choose_composite_windows(" in src  # v5g: multi-clip composite
    assert "OWNER_QWEN_COMPOSITE_PARTS=" in src
    assert src.index("validate_qwen_reference(")<src.index("model.create_voice_clone_prompt(\n        ref_audio=str(canonical24)")
