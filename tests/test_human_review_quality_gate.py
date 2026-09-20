from app.services.human_review_quality_gate import (
    validate_content_duration,
    validate_media_novelty,
    validate_text_overlay_contract,
)


def test_structural_text_is_rejected_even_when_not_caption_track():
    result = validate_text_overlay_contract(
        texts=[{"text": "Hook", "track": "T1"}, {"text": "Introdução", "track": "T2"}],
        planned_text_overlays=[],
    )
    assert result["status"] == "FAIL"
    assert result["STRUCTURAL_LABEL_OVERLAY"] == "ON"
    assert result["UNPLANNED_TEXT_OVERLAY"] == "ON"


def test_master_with_no_text_is_clean():
    result = validate_text_overlay_contract(texts=[], planned_text_overlays=[])
    assert result["status"] == "PASS"
    assert result["STRUCTURAL_LABEL_OVERLAY"] == "OFF"
    assert result["DEBUG_OVERLAY"] == "OFF"
    assert result["BURNED_SUBTITLES"] == "OFF"
    assert result["OPEN_CAPTIONS"] == "OFF"
    assert result["TRANSCRIPT_OVERLAY"] == "OFF"
    assert result["UNPLANNED_TEXT_OVERLAY"] == "OFF"


def test_ten_minutes_cannot_pass_longform_content_gate():
    result = validate_content_duration(
        target_duration_seconds=600,
        content_supported_duration_seconds=600,
        artificial_padding=False,
    )
    assert result["status"] == "FAIL"
    assert result["TARGET_DURATION_MINUTES_GTE_20"] is False
    assert result["CONTENT_SUPPORTED_DURATION_GTE_20"] is False


def test_real_target_fully_supported_without_padding_passes():
    result = validate_content_duration(
        target_duration_seconds=1320,
        content_supported_duration_seconds=1320,
        artificial_padding=False,
    )
    assert result["status"] == "PASS"
    assert result["CONTENT_SUPPORTS_TARGET"] is True
    assert result["ARTIFICIAL_PADDING"] == "OFF"


def test_single_source_cannot_fake_media_novelty_with_many_windows():
    links = [
        {"asset_ref": "remote://old", "duration_seconds": 8.0, "source_start_seconds": i * 8.0}
        for i in range(100)
    ]
    result = validate_media_novelty(semantic_links=links)
    assert result["status"] == "FAIL"
    assert result["unique_asset_count"] == 1


def test_diverse_media_with_low_previous_reuse_passes():
    links = []
    for ref in ("a", "b", "c", "d"):
        links.extend({"asset_ref": ref, "duration_seconds": 10.0} for _ in range(5))
    result = validate_media_novelty(semantic_links=links, previous_asset_refs=("old-x",))
    assert result["status"] == "PASS"


def test_target_above_25_minutes_is_rejected_for_video_a_band():
    result = validate_content_duration(
        target_duration_seconds=26*60,
        content_supported_duration_seconds=26*60,
        artificial_padding=False,
    )
    assert result["status"]=="FAIL"
    assert result["TARGET_DURATION_WITHIN_20_25"] is False


def test_content_must_support_full_target_not_only_twenty_minutes():
    result = validate_content_duration(
        target_duration_seconds=24*60,
        content_supported_duration_seconds=20*60,
        artificial_padding=False,
    )
    assert result["status"]=="FAIL"
    assert result["CONTENT_SUPPORTED_DURATION_GTE_20"] is True
    assert result["CONTENT_SUPPORTS_TARGET"] is False


def test_locked_voice_b_planning_rate_requires_about_3400_words_for_20_minutes():
    from app.services.human_review_quality_gate import VOICE_B_CONTENT_PLANNING_WPM
    required=20*VOICE_B_CONTENT_PLANNING_WPM
    assert required==3400.0
