from __future__ import annotations

import pytest

from scripts.owner_voice_reference_qa import build_reference_candidate, build_reference_qa_context


def _materialized(input_id: int) -> dict:
    return {
        "telegram_input_id": input_id,
        "runtime_path": f"/tmp/ref-{input_id}.ogg",
        "private_audio_ref": f"private://voice/BR_OWNER_V1/references/{input_id:064x}",
        "sha256": f"{input_id:064x}",
        "duration_seconds": 8.0,
    }


def _metrics() -> dict:
    return {
        "duration_seconds": 8.0,
        "sample_rate_hz": 16000,
        "channels": 1,
        "clipping_ratio": 0.0,
        "snr_db": 26.0,
        "speech_ratio": 0.88,
        "silence_ratio": 0.12,
        "rms_dbfs": -18.0,
        "peak_dbfs": -4.0,
    }


def test_reference_candidate_binds_real_telegram_audio_to_portuguese_qa():
    row = build_reference_candidate(
        reference=_materialized(7),
        normalized_path="/tmp/ref-7.wav",
        metrics=_metrics(),
        detected_language="pt",
        language_probability=0.98,
        transcription_confidence=0.94,
        transcript="A gente vai testar a voz em português do Brasil.",
    )
    assert row["reference_source"] == "TELEGRAM"
    assert row["voice_identity_id"] == "BR_OWNER_V1"
    assert row["ptbr_probability"] == 0.98
    assert row["quality_score"] > 0.85
    assert row["runtime_path"] == "/tmp/ref-7.wav"
    assert row["transcript_private_only"] is True


def test_non_portuguese_reference_cannot_be_identity_grade():
    row = build_reference_candidate(
        reference=_materialized(7),
        normalized_path="/tmp/ref-7.wav",
        metrics=_metrics(),
        detected_language="en",
        language_probability=0.99,
        transcription_confidence=0.94,
        transcript="Non Portuguese reference.",
    )
    assert row["ptbr_probability"] == 0.0
    with pytest.raises(ValueError, match="OWNER_REFERENCE_NO_IDENTITY_GRADE_CANDIDATE"):
        build_reference_qa_context([row])


def test_quality_context_selects_best_not_latest_and_keeps_transcript_private():
    weaker = build_reference_candidate(
        reference=_materialized(99),
        normalized_path="/tmp/ref-99.wav",
        metrics={**_metrics(), "snr_db": 16.0, "clipping_ratio": 0.006},
        detected_language="pt",
        language_probability=0.91,
        transcription_confidence=0.82,
        transcript="Teste mais fraco.",
    )
    better = build_reference_candidate(
        reference=_materialized(12),
        normalized_path="/tmp/ref-12.wav",
        metrics=_metrics(),
        detected_language="pt",
        language_probability=0.99,
        transcription_confidence=0.96,
        transcript="Teste limpo da voz real.",
    )
    context = build_reference_qa_context([weaker, better])
    assert context["schema"] == "OwnerVoiceReferenceQAContext/v1"
    assert context["voice_identity_id"] == "BR_OWNER_V1"
    assert context["reference_source"] == "TELEGRAM"
    assert context["locale"] == "pt-BR"
    assert context["selected_telegram_input_id"] == 12
    assert context["latest_input_wins"] is False
    assert "transcript" not in context
    assert context["private_transcript_available"] is True
