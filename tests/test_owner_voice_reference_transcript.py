from __future__ import annotations

import json

import pytest

from scripts.owner_voice_reference_transcript import (
    build_private_transcript_context,
)


def test_private_transcript_context_is_bound_to_real_reference_without_telegram_identifiers():
    context = build_private_transcript_context(
        telegram_input_id=54,
        audio_sha256="a" * 64,
        transcript="Booooa meu povo, aqui é BR no GTA 6.",
        language="pt",
        language_probability=0.99,
        transcription_confidence=0.93,
        model_id="small",
    )
    assert context["schema"] == "OwnerVoicePrivateTranscript/v1"
    assert context["telegram_input_id"] == 54
    assert context["audio_sha256"] == "a" * 64
    assert context["transcript"].startswith("Booooa meu povo")
    assert context["language"] == "pt"
    assert context["language_probability"] == 0.99
    assert context["transcription_confidence"] == 0.93
    serialized = json.dumps(context, sort_keys=True)
    assert "telegram_file_id" not in serialized
    assert "telegram_file_unique_id" not in serialized
    assert "telegram_chat_id" not in serialized


@pytest.mark.parametrize(
    ("transcript", "language", "language_probability"),
    [
        ("", "pt", 0.99),
        ("fala válida", "en", 0.99),
        ("fala válida", "pt", 0.20),
    ],
)
def test_private_transcript_context_fails_closed_on_unusable_asr(
    transcript,
    language,
    language_probability,
):
    with pytest.raises(ValueError):
        build_private_transcript_context(
            telegram_input_id=54,
            audio_sha256="a" * 64,
            transcript=transcript,
            language=language,
            language_probability=language_probability,
            transcription_confidence=0.90,
            model_id="small",
        )
