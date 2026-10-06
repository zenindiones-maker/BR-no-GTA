from __future__ import annotations

from app.services.owner_voice_audition_performance_service import (
    REFERENCE_SELECTION_SCHEMA,
    build_reference_selection_receipt,
    build_selection_policy_hash,
    build_stt_contract_hash,
    validate_reference_selection_receipt,
)


def test_reference_selection_receipt_is_sanitized_and_content_bound():
    receipt=build_reference_selection_receipt(
        reference_set_digest="a"*64,
        selection_policy_hash=build_selection_policy_hash(),
        stt_contract_hash=build_stt_contract_hash("large-v3-turbo"),
        selected_telegram_input_id=17,
        selected_audio_sha256="b"*64,
        quality_score=0.97,
        ptbr_probability=0.99,
        transcription_confidence=0.95,
    )
    assert receipt["schema_version"]==REFERENCE_SELECTION_SCHEMA
    assert receipt["reference_source"]=="TELEGRAM"
    assert receipt["voice_identity_id"]=="BR_OWNER_V1"
    assert len(receipt["content_sha256"])==64
    forbidden={
        "audio_bytes","raw_audio","transcript","telegram_bot_token",
        "file_bytes","voice_embedding","chatterbox_conditionals","telegram_file_id",
    }
    assert forbidden.isdisjoint(receipt)
    assert validate_reference_selection_receipt(
        receipt,
        reference_set_digest="a"*64,
        selection_policy_hash=receipt["selection_policy_hash"],
        stt_contract_hash=receipt["stt_contract_hash"],
    ) is True


def test_reference_selection_receipt_invalidates_on_reference_or_contract_change():
    receipt=build_reference_selection_receipt(
        reference_set_digest="a"*64,
        selection_policy_hash=build_selection_policy_hash(),
        stt_contract_hash=build_stt_contract_hash("large-v3-turbo"),
        selected_telegram_input_id=17,
        selected_audio_sha256="b"*64,
        quality_score=0.97,
        ptbr_probability=0.99,
        transcription_confidence=0.95,
    )
    assert validate_reference_selection_receipt(
        receipt,
        reference_set_digest="c"*64,
        selection_policy_hash=receipt["selection_policy_hash"],
        stt_contract_hash=receipt["stt_contract_hash"],
    ) is False


def test_long_form_qualification_requires_explicit_human_selected_candidate():
    from app.services.owner_voice_qualification_stage_service import (
        build_long_form_qualification,
    )
    import pytest
    with pytest.raises(ValueError,match="HUMAN_APPROVED_CANDIDATE_REQUIRED"):
        build_long_form_qualification(human_approved=None)
    contract=build_long_form_qualification(human_approved="B")
    assert contract["stage"]=="LONG_FORM_VOICE_QUALIFICATION"
    assert contract["human_approved"]=="B"
    assert contract["voice_identity_id"]=="BR_OWNER_V1"
    assert contract["reference_source"]=="TELEGRAM_HUMAN_OWNER"
    assert "Vice City" in contract["text"]
    assert "Leonida" in contract["text"]
    assert "Rockstar" in contract["text"]
