from __future__ import annotations

import pytest

from scripts.owner_voice_qwen_ephemeral_audition import (
    QWEN_REQUIRED_SNAPSHOT_PATHS,
    load_verified_transcript_context,
    select_latest_reference,
    validate_qwen_snapshot,
)
from app.services.owner_voice_private_materialization_service import (
    OwnerVoicePrivateMaterializationError,
)


def test_latest_real_telegram_reference_is_selected_for_first_audition():
    selected = select_latest_reference(
        [
            {
                "telegram_input_id": 49,
                "runtime_path": "/tmp/ref-49.ogg",
                "sha256": "a" * 64,
            },
            {
                "telegram_input_id": 50,
                "runtime_path": "/tmp/ref-50.ogg",
                "sha256": "b" * 64,
            },
        ]
    )
    assert selected["telegram_input_id"] == 50
    assert selected["sha256"] == "b" * 64


def test_audition_selection_fails_closed_without_materialized_reference():
    with pytest.raises(
        OwnerVoicePrivateMaterializationError,
        match="OWNER_REFERENCE_DISCOVERY_EMPTY",
    ):
        select_latest_reference([])


def test_qwen_snapshot_requires_complete_embedded_speech_tokenizer(tmp_path):
    for relative in QWEN_REQUIRED_SNAPSHOT_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    assert validate_qwen_snapshot(tmp_path) == tmp_path

    missing = tmp_path / "speech_tokenizer" / "preprocessor_config.json"
    missing.unlink()
    with pytest.raises(
        OwnerVoicePrivateMaterializationError,
        match="QWEN_SNAPSHOT_INCOMPLETE",
    ):
        validate_qwen_snapshot(tmp_path)


def test_qwen_clone_requires_matching_private_transcript_context(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text(
        """{
          "schema": "OwnerVoicePrivateTranscript/v1",
          "telegram_input_id": 50,
          "audio_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "language": "pt",
          "language_probability": 0.98,
          "transcription_confidence": 0.91,
          "transcript": "Teste real da voz do dono do canal."
        }""",
        encoding="utf-8",
    )
    text = load_verified_transcript_context(
        path,
        telegram_input_id=50,
        audio_sha256="b" * 64,
    )
    assert text == "Teste real da voz do dono do canal."

    with pytest.raises(
        OwnerVoicePrivateMaterializationError,
        match="OWNER_REFERENCE_TRANSCRIPT_MISMATCH",
    ):
        load_verified_transcript_context(
            path,
            telegram_input_id=49,
            audio_sha256="b" * 64,
        )
