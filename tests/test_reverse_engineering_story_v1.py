from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.reverse_engineering_media_service import ObservationError
from app.services.reverse_engineering_story_service import analyze_script_structure


def test_structural_script_metrics_never_copy_dialogue(tmp_path):
    script=tmp_path/"original.txt"
    script.write_text("Booooa meu povo, teste inicial!\nQual detalhe você percebeu?\n",encoding="utf-8")
    result=analyze_script_structure(script)
    assert result["schema_version"]=="BRNarrativeTimingObservation/v1"
    assert result["analysis"]["timing_observed"] is False
    assert result["analysis"]["exclamation_mark_count"]==1
    assert result["analysis"]["question_mark_count"]==1
    assert result["analysis"]["semantic_arc_verified"] is False
    assert "percebeu" not in json.dumps(result,ensure_ascii=False)


def test_srt_structure_has_binned_timing_overlap_and_no_spoken_wpm(tmp_path):
    file=tmp_path/"subtitles.srt"
    file.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nUma nova cena começa\n\n"
        "2\n00:00:01,500 --> 00:00:04,000\nMas a fala se sobrepõe\n\n"
        "3\n00:00:08,000 --> 00:00:09,000\nFinal\n",encoding="utf-8"
    )
    result=analyze_script_structure(file,media_duration_seconds=10)
    a=result["analysis"]
    assert a["cue_count"]==3
    assert a["overlapping_cue_count"]==1
    assert a["word_count"]==10
    assert sum(a["timeline_words_12_bins"])==10
    assert a["actual_speaking_rate_wpm"] is None
    assert a["semantic_arc_verified"] is False
    assert "Uma nova cena" not in json.dumps(result)


def test_srt_timing_exceeding_media_is_blocked(tmp_path):
    file=tmp_path/"off.srt"
    file.write_text("1\n00:00:00,000 --> 00:00:09,000\nToo late\n")
    with pytest.raises(ObservationError,match="STORY_CUES_EXCEED_MEDIA_DURATION"):
        analyze_script_structure(file,media_duration_seconds=3)


def test_bad_input_and_symbolic_link_fail_closed(tmp_path):
    file=tmp_path/"bad.srt"
    file.write_text("1\n00:00:04,000 --> 00:00:02,000\nBad\n")
    with pytest.raises(ObservationError,match="STORY_CUE_TIME_INVALID"):
        analyze_script_structure(file)
    link=tmp_path/"link.srt"
    link.symlink_to(file)
    with pytest.raises(ObservationError,match="SOURCE_MISSING_OR_SYMLINK"):
        analyze_script_structure(link)
