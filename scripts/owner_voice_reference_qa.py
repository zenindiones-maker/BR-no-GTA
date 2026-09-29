from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.services.owner_voice_audio_quality_service import score_owner_reference_quality
from app.services.owner_voice_clone_service import select_owner_reference


VOICE_IDENTITY_ID = "BR_OWNER_V1"
REFERENCE_SOURCE = "TELEGRAM"
EXTERNAL_LOCALE = "pt-BR"


def _language(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def build_reference_candidate(
    *,
    reference: Mapping[str, Any],
    normalized_path: str,
    metrics: Mapping[str, Any],
    detected_language: str,
    language_probability: float,
    transcription_confidence: float,
    transcript: str,
) -> dict[str, Any]:
    text_present = bool(" ".join(str(transcript or "").split()).strip())
    lang = _language(detected_language)
    probability = max(0.0, min(1.0, float(language_probability)))
    confidence = max(0.0, min(1.0, float(transcription_confidence)))
    ptbr_probability = probability if lang in {"pt", "pt-br"} else 0.0
    quality_score = score_owner_reference_quality(
        metrics,
        ptbr_probability=ptbr_probability,
        transcription_confidence=confidence,
    )
    return {
        **dict(reference),
        **dict(metrics),
        "voice_identity_id": VOICE_IDENTITY_ID,
        "reference_source": REFERENCE_SOURCE,
        "locale": EXTERNAL_LOCALE,
        "runtime_path": str(normalized_path),
        "detected_language": lang,
        "language_probability": probability,
        "ptbr_probability": ptbr_probability,
        "transcription_confidence": confidence,
        "quality_score": quality_score,
        "transcript_private_only": True,
        "transcript_present": text_present,
    }


def build_reference_qa_context(
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in candidates]
    selected = select_owner_reference(rows)
    if selected.get("transcript_present") is not True:
        raise ValueError("OWNER_REFERENCE_TRANSCRIPT_REQUIRED")
    return {
        "schema": "OwnerVoiceReferenceQAContext/v1",
        "voice_identity_id": VOICE_IDENTITY_ID,
        "reference_source": REFERENCE_SOURCE,
        "locale": EXTERNAL_LOCALE,
        "selected_telegram_input_id": int(selected["telegram_input_id"]),
        "selected_audio_sha256": str(selected["sha256"]),
        "selected_private_audio_ref": str(selected["private_audio_ref"]),
        "selection_policy": str(selected["selection_policy"]),
        "latest_input_wins": False,
        "quality_score": float(selected["quality_score"]),
        "ptbr_probability": float(selected["ptbr_probability"]),
        "transcription_confidence": float(selected["transcription_confidence"]),
        "snr_db": float(selected.get("snr_db") or 0.0),
        "clipping_ratio": float(selected.get("clipping_ratio") or 0.0),
        "speech_ratio": float(selected.get("speech_ratio") or 0.0),
        "private_transcript_available": True,
    }
