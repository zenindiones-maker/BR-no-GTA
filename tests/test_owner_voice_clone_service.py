from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.owner_voice_clone_service import (
    QWEN_OWNER_MODEL_ID,
    QWEN_OWNER_MODEL_REVISION,
    QWEN_TTS_VERSION,
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
        "transcript": "Booooa meu povo, aqui é BR no GTA 6.",
    }


def test_reference_selection_is_quality_first_not_latest_message():
    selected = select_owner_reference(
        [
            _ref(99, quality=0.40, duration=8.0),
            _ref(12, quality=0.96, duration=10.1),
            _ref(13, quality=0.90, duration=9.9),
        ]
    )
    assert selected["telegram_input_id"] == 12
    assert selected["selection_policy"] == "QUALITY_FIRST_DETERMINISTIC"
    assert selected["latest_input_wins"] is False


def test_reference_selection_rejects_non_ptbr_or_multiple_speakers():
    with pytest.raises(ValueError, match="OWNER_REFERENCE_NO_IDENTITY_GRADE_CANDIDATE"):
        select_owner_reference(
            [
                _ref(1, quality=0.99, duration=10.0, single_speaker=False),
                _ref(2, quality=0.99, duration=10.0, ptbr_probability=0.40),
            ]
        )


def test_qwen_clone_request_is_bound_to_owner_reference_and_transcript():
    request = build_ptbr_clone_request(
        reference=_ref(12, quality=0.96, duration=10.1),
        text="Booooa meu povo, aqui é BR no GTA 6.",
        seed=424242,
    )
    assert request["schema"] == "OwnerVoiceQwenCloneRequest/v2"
    assert request["voice_identity_id"] == "BR_OWNER_V1"
    assert request["reference_source"] == "TELEGRAM"
    assert request["locale"] == "pt-BR"
    assert request["language"] == "Portuguese"
    assert request["model_id"] == QWEN_OWNER_MODEL_ID
    assert request["model_revision"] == QWEN_OWNER_MODEL_REVISION
    assert request["qwen_tts_version"] == QWEN_TTS_VERSION
    assert request["ref_audio_path"].endswith("ref-12.wav")
    assert request["ref_text"] == "Booooa meu povo, aqui é BR no GTA 6."
    assert request["x_vector_only_mode"] is False
    assert request["one_candidate_only"] is True
    assert request["provider_preset_voice_allowed"] is False
    assert request["provider_default_voice_allowed"] is False
    assert request["generic_voice_fallback"] is False
    assert "speaker" not in request
    assert "voice_name" not in request
    assert "cfg_weight" not in request
    assert "exaggeration" not in request


def test_qwen_clone_request_requires_bound_telegram_reference():
    ref = _ref(12, quality=0.96, duration=10.1)
    ref["private_audio_ref"] = "provider://default"
    with pytest.raises(ValueError, match="OWNER_TELEGRAM_REFERENCE_REQUIRED"):
        build_ptbr_clone_request(
            reference=ref,
            text="Teste curto.",
            seed=424242,
        )


def test_qwen_icl_requires_reference_transcript():
    ref = _ref(12, quality=0.96, duration=10.1)
    ref["transcript"] = ""
    with pytest.raises(ValueError, match="OWNER_REFERENCE_TRANSCRIPT_REQUIRED"):
        build_ptbr_clone_request(
            reference=ref,
            text="Teste curto.",
            seed=424242,
        )


def test_audition_builder_is_one_candidate_deterministic_and_qwen_only():
    variants = build_ptbr_audition_variants(
        reference=_ref(12, quality=0.96, duration=10.1),
        text="Hoje a gente vai falar de GTA 6 em português brasileiro.",
    )
    assert len(variants) == 1
    request = variants[0]
    assert request["one_candidate_only"] is True
    assert request["locale"] == "pt-BR"
    assert request["language"] == "Portuguese"
    assert request["seed"] == 424242
    assert request["model_id"] == QWEN_OWNER_MODEL_ID
    assert request["ref_audio_path"].endswith("ref-12.wav")


def test_qwen_model_and_runtime_are_content_pinned():
    assert QWEN_OWNER_MODEL_ID == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert QWEN_OWNER_MODEL_REVISION == "fd4b254389122332181a7c3db7f27e918eec64e3"
    assert QWEN_TTS_VERSION == "0.1.1"


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
