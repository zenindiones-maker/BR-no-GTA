from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.owner_voice_clone_service import (
    CHATTERBOX_PTBR_MODEL_ID,
    CHATTERBOX_PTBR_T3_SHA256,
    CHATTERBOX_PTBR_S3GEN_SHA256,
    build_ptbr_audition_variants,
    build_ptbr_clone_request,
    select_owner_reference,
)


ROOT = Path(__file__).resolve().parents[1]


def _ref(
    input_id: int,
    *,
    quality: float,
    duration: float,
    single_speaker: bool = True,
    ptbr_probability: float = 0.99,
) -> dict:
    return {
        "telegram_input_id": input_id,
        "runtime_path": f"/tmp/owner/ref-{input_id}.wav",
        "private_audio_ref": f"private://voice/BR_OWNER_V1/references/{input_id:064x}",
        "sha256": f"{input_id:064x}",
        "duration_seconds": duration,
        "quality_score": quality,
        "single_speaker": single_speaker,
        "ptbr_probability": ptbr_probability,
        "clipping_ratio": 0.0,
        "snr_db": 28.0,
        "speech_ratio": 0.92,
    }


def test_reference_selection_is_quality_first_not_latest_message():
    selected = select_owner_reference(
        [
            _ref(99, quality=0.40, duration=8.0),
            _ref(12, quality=0.96, duration=8.1),
            _ref(13, quality=0.90, duration=7.9),
        ]
    )
    assert selected["telegram_input_id"] == 12
    assert selected["selection_policy"] == "QUALITY_FIRST_DETERMINISTIC"
    assert selected["latest_input_wins"] is False


def test_reference_selection_rejects_non_ptbr_or_multiple_speakers():
    with pytest.raises(ValueError, match="OWNER_REFERENCE_NO_IDENTITY_GRADE_CANDIDATE"):
        select_owner_reference(
            [
                _ref(1, quality=0.99, duration=8.0, single_speaker=False),
                _ref(2, quality=0.99, duration=8.0, ptbr_probability=0.40),
            ]
        )


def test_ptbr_clone_request_has_no_provider_or_default_voice_path():
    request = build_ptbr_clone_request(
        reference=_ref(12, quality=0.96, duration=8.1),
        text="Booooa meu povo, aqui é BR no GTA 6.",
        cfg_weight=0.3,
        seed=424242,
    )
    assert request["voice_identity_id"] == "BR_OWNER_V1"
    assert request["reference_source"] == "TELEGRAM"
    assert request["locale"] == "pt-BR"
    assert request["language_id"] == "pt"
    assert request["model_id"] == CHATTERBOX_PTBR_MODEL_ID
    assert request["audio_prompt_path"].endswith("ref-12.wav")
    assert request["provider_preset_voice_allowed"] is False
    assert request["provider_default_voice_allowed"] is False
    assert request["generic_voice_fallback"] is False
    assert "speaker" not in request
    assert "voice_name" not in request


def test_ptbr_clone_request_requires_bound_telegram_reference():
    ref = _ref(12, quality=0.96, duration=8.1)
    ref["private_audio_ref"] = "provider://default"
    with pytest.raises(ValueError, match="OWNER_TELEGRAM_REFERENCE_REQUIRED"):
        build_ptbr_clone_request(
            reference=ref,
            text="Teste curto.",
            cfg_weight=0.3,
            seed=424242,
        )


def test_audition_matrix_is_small_deterministic_and_ptbr_only():
    variants = build_ptbr_audition_variants(
        reference=_ref(12, quality=0.96, duration=8.1),
        text="Hoje a gente vai falar de GTA 6 em português brasileiro.",
    )
    assert [row["cfg_weight"] for row in variants] == [0.3, 0.5, 0.7]
    assert {row["locale"] for row in variants} == {"pt-BR"}
    assert {row["language_id"] for row in variants} == {"pt"}
    assert {row["seed"] for row in variants} == {424242}
    assert all(row["audio_prompt_path"].endswith("ref-12.wav") for row in variants)


def test_ptbr_model_artifacts_are_content_pinned():
    assert CHATTERBOX_PTBR_MODEL_ID == "ResembleAI/Chatterbox-Multilingual-pt-br"
    assert CHATTERBOX_PTBR_T3_SHA256 == "074aaf65255eb9cb960288f7cc72e09d3b5008f6e0b14868c0d4e5b0bd7cbb6c"
    assert CHATTERBOX_PTBR_S3GEN_SHA256 == "4a46190f3dccc2230fbb3488a930bccc925862ee68f2662433dfcfe93ce6c2cb"


def test_clone_mission_forbids_every_non_owner_voice():
    mission = json.loads(
        (ROOT / "config/owner_voice_clone_mission_v1.json").read_text(encoding="utf-8")
    )
    assert mission["voice_identity_id"] == "BR_OWNER_V1"
    assert mission["identity_source"]["transport"] == "TELEGRAM"
    assert mission["identity_source"]["other_voice_references_allowed"] is False
    assert mission["identity_source"]["provider_default_voice_allowed"] is False
    assert mission["identity_source"]["provider_preset_voice_allowed"] is False
    assert mission["identity_source"]["generic_voice_fallback_allowed"] is False
    assert mission["language"]["required_locale"] == "pt-BR"
    assert mission["language"]["pt_PT_allowed"] is False
    assert mission["language"]["foreign_accent_acceptance"] is False
