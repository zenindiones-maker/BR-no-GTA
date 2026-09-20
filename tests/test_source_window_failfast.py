from __future__ import annotations

import pytest

import app.workers.professional_audiovisual_worker as professional
from app.services.source_window_validation_service import validate_source_window_usage


def _brand_contract():
    return {
        "opening_text": "Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de teste!",
        "closing_line": "E BR não dorme em Vice City",
        "official_voice_profile": "Voice B",
        "cache_policy": {"closing_fixed_reusable": True},
    }


def test_real_late_qa_overlap_is_classified_with_exact_windows():
    result = validate_source_window_usage([
        {
            "segment_id": 2,
            "section_id": "benchmark-script-01",
            "asset_ref": "remote://media-worker/current",
            "source_start_seconds": 11.928,
            "duration_seconds": 6.0,
        },
        {
            "segment_id": 5,
            "section_id": "benchmark-script-01",
            "asset_ref": "remote://media-worker/current",
            "source_start_seconds": 11.928,
            "duration_seconds": 4.941578,
        },
    ])
    assert result["status"] == "FAIL"
    assert result["overlap_count"] == 1
    defect = result["overlaps"][0]
    assert defect["previous_segment_id"] == 5 or defect["previous_segment_id"] == 2
    assert defect["overlap_seconds"] == pytest.approx(4.941578, abs=1e-6)


def test_allocator_spills_forward_without_rewinding_first_window(monkeypatch):
    monkeypatch.setattr(professional, "validate_job_spoken_branding", lambda job: _brand_contract())
    job = {
        "script_sections": [
            {
                "section_id": "benchmark-script-01",
                "heading": "Hook",
                "narration": "x",
                "classification": "ANALYSIS",
                "evidence_ids": ["e1"],
                "role": "hook",
                "visual_candidates": [{
                    "asset_ref": "remote://media-worker/current",
                    "start_seconds": 0.0,
                    "end_seconds": 40.5,
                }],
            },
            {
                "section_id": "benchmark-script-02",
                "heading": "Body",
                "narration": "y",
                "classification": "ANALYSIS",
                "evidence_ids": ["e1"],
                "role": "cta",
                "visual_candidates": [{
                    "asset_ref": "remote://media-worker/current",
                    "start_seconds": 40.5,
                    "end_seconds": 63.0,
                }],
            },
        ],
        "media_sources": [{
            "asset_ref": "remote://media-worker/current",
            "source_url": "https://www.youtube.com/watch?v=test",
        }],
    }
    opening = 11.928
    closing = 3.462
    first = 28.941578427736587
    second = 13.222893626602703
    voice_sections = [
        {"section_id": "benchmark-script-01", "duration_seconds": first},
        {"section_id": "benchmark-script-02", "duration_seconds": second},
    ]
    plan, edit_qa, _ = professional._build_edit_plan(
        job,
        voice_sections,
        {"remote://media-worker/current": "current.mp4"},
        narration_master_path="voice.flac",
        narration_duration=opening + first + second + closing,
        brand_audio={
            "opening_duration_seconds": opening,
            "closing_duration_seconds": closing,
        },
    )
    assert plan.duration_seconds == pytest.approx(opening + first + second + closing)
    assert edit_qa["status"] == "PASS"
    assert edit_qa["source_window_validation"]["status"] == "PASS"
    links = edit_qa["semantic_links"]
    first_section = [x for x in links if x["section_id"] == "benchmark-script-01"]
    assert first_section[-1]["source_start_seconds"] > 35.9
    assert first_section[-1]["source_start_seconds"] + first_section[-1]["duration_seconds"] > 40.5
    assert edit_qa["source_window_validation"]["overlap_count"] == 0
