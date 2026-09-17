from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.run001_longform_editorial_controller import validate_config
from scripts.run001_longform_no_padding_qa import validate_no_padding


ROOT = Path(__file__).resolve().parents[1]
VIDEO_A = ROOT / ".run001" / "video-a-investigative-longform.json"


def _config():
    return json.loads(VIDEO_A.read_text(encoding="utf-8"))


def test_video_a_contract_is_independent_longform_ptbr_and_review_only():
    config = _config()
    metrics = validate_config(config)
    assert config["product_label"] == "A"
    assert config["target_language"] == "pt-BR"
    assert config["render_job_id"] == config["video_id"] == 920101
    assert config["render_job_id"] not in {18, 20}
    assert config["youtube_publication"] is False
    assert 2600 <= metrics["word_count"] <= 5200
    assert 1200 <= metrics["estimated_spoken_duration"] <= 1800
    assert metrics["target_wpm"] == 125.0
    assert len({section["section_id"] for section in config["script_sections"]}) == len(config["script_sections"])


def test_job18_and_job20_are_hard_blocked_as_final_products():
    for forbidden in (18, 20):
        config = _config()
        config["render_job_id"] = forbidden
        with pytest.raises(ValueError, match="Job18 is frozen|Job20"):
            validate_config(config)


def test_youtube_publication_cannot_be_enabled():
    config = _config()
    config["youtube_publication"] = True
    with pytest.raises(ValueError, match="cannot publish to YouTube"):
        validate_config(config)


def test_duplicate_section_narration_is_rejected():
    config = _config()
    config["script_sections"][1]["narration"] = config["script_sections"][0]["narration"]
    with pytest.raises(ValueError, match="duplicate narration"):
        validate_config(config)


def test_short_script_cannot_pass_longform_duration_gate():
    config = _config()
    for section in config["script_sections"]:
        section["narration"] = "Este é um trecho curto em português que não sustenta um produto long-form profissional com investigação real."
    with pytest.raises(ValueError, match="word count outside professional range|does not sustain"):
        validate_config(config)


def test_no_padding_qa_accepts_unique_contiguous_source_windows():
    job = {"product_profile": "professional_ptbr_v1", "render_job_id": 920101, "youtube_publication": False}
    links = []
    for index in range(120):
        links.append({
            "segment_id": index + 1,
            "section_id": f"S{index // 10:02d}",
            "asset_ref": "remote://media-worker/official-longform",
            "source_start_seconds": index * 10.0,
            "duration_seconds": 10.0,
        })
    result = validate_no_padding(job=job, edit_qa={"duration_seconds": 1200.0, "semantic_links": links})
    assert result["NO_ARTIFICIAL_PADDING"] == "PASS"
    assert result["NO_REPEATED_SOURCE_WINDOWS"] == "PASS"


def test_no_padding_qa_rejects_source_reuse():
    job = {"product_profile": "professional_ptbr_v1", "render_job_id": 920101, "youtube_publication": False}
    links = []
    for index in range(120):
        start = index * 10.0
        if index == 119:
            start = 0.0
        links.append({
            "segment_id": index + 1,
            "section_id": f"S{index // 10:02d}",
            "asset_ref": "remote://media-worker/official-longform",
            "source_start_seconds": start,
            "duration_seconds": 10.0,
        })
    with pytest.raises(RuntimeError, match="source windows were reused or overlapped"):
        validate_no_padding(job=job, edit_qa={"duration_seconds": 1200.0, "semantic_links": links})
