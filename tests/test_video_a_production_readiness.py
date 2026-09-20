from __future__ import annotations

from app.services.video_a_production_readiness import (
    static_readiness_report,
    validate_persisted_readiness,
)


def test_static_readiness_preserves_green_editorial_but_fails_audio_and_visual():
    result=static_readiness_report()
    assert result["candidate_id"]=="video-a-next-candidate-20260920-social-vice-city"
    assert result["human_state"]["feedback"]["technical_pass_but_perceptual_fail"] is True
    assert result["GLOBAL_DUBBING_QUALITY"]=="FAIL"
    assert result["GLOBAL_PRONUNCIATION_STATUS"]=="FAIL"
    assert result["LEONIDA_PRONUNCIATION"]=="FAIL"
    assert result["PRODUCTION_READINESS"]=="FAIL"
    assert result["FULL_RENDER_AUTHORIZED"]=="NO"
    assert result["chunking"]["CURRENT_SEGMENT_STRATEGY"]=="microsegment-v1"
    assert result["chunking"]["BASELINE_SEGMENT_STRATEGY"]=="semantic-section-v1"
    assert result["chunking"]["NARRATION_SEGMENTS_TOTAL"] > result["chunking"]["BASELINE_NARRATION_SEGMENTS_TOTAL"]
    assert result["claims"]["UNSUPPORTED_CLAIMS"]==0
    assert result["claims"]["CLAIM_EVIDENCE_COVERAGE"]==100.0
    assert result["visual"]["UNPLANNED_TEXT_OVERLAY"]=="OFF"
    assert result["visual"]["VISUAL_COVERAGE"]=="FAIL"
    assert result["pronunciation"]["PRONUNCIATION_TERMS_TOTAL"] > 10
    assert result["pronunciation"]["PRONUNCIATION_COVERAGE_PERCENT"] < 100.0
    assert result["pronunciation"]["UNVALIDATED_PROPER_NOUNS"]


def test_persisted_hard_gate_fails_closed_on_current_human_rejection():
    result=validate_persisted_readiness()
    assert result["status"]=="FAIL"
    assert result["PRODUCTION_READINESS"]=="FAIL"
    assert result["FULL_RENDER_AUTHORIZED"]=="NO"
    assert "HUMAN_VOICE_REVIEW" in result["failed"]
    assert "GLOBAL_PRONUNCIATION_STATUS" in result["failed"]
    assert "VISUAL_COVERAGE" in result["failed"]
