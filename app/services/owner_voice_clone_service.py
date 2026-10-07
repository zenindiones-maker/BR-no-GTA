from __future__ import annotations

from typing import Any, Iterable, Mapping


VOICE_IDENTITY_ID = "BR_OWNER_V1"
REFERENCE_SOURCE = "TELEGRAM"
EXTERNAL_LOCALE = "pt-BR"
QWEN_OWNER_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
QWEN_OWNER_MODEL_REVISION = "fd4b254389122332181a7c3db7f27e918eec64e3"
QWEN_TTS_VERSION = "0.1.1"
QWEN_CLONE_MODE = "TRANSCRIPT_CONDITIONED_ICL"
QWEN_GENERATION_CONFIG = {
    "do_sample": True,
    "top_k": 50,
    "top_p": 1.0,
    "temperature": 0.9,
    "repetition_penalty": 1.05,
    "subtalker_dosample": True,
    "subtalker_top_k": 50,
    "subtalker_top_p": 1.0,
    "subtalker_temperature": 0.9,
}
PREFERRED_REFERENCE_SECONDS_MIN = 6.0
PREFERRED_REFERENCE_SECONDS_MAX = 15.0
PREFERRED_REFERENCE_SECONDS_TARGET = 10.0
PTBR_REFERENCE_PROBABILITY_MIN = 0.90
SNR_DB_MIN = 15.0
CLIPPING_RATIO_MAX = 0.01
SPEECH_RATIO_MIN = 0.55


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _identity_grade(row: Mapping[str, Any]) -> bool:
    private_ref = str(row.get("private_audio_ref") or "").strip()
    runtime_path = str(row.get("runtime_path") or "").strip()
    digest = str(row.get("sha256") or "").strip().lower()
    return bool(
        int(row.get("telegram_input_id") or 0) > 0
        and runtime_path
        and private_ref.startswith(f"private://voice/{VOICE_IDENTITY_ID}/")
        and len(digest) == 64
        and all(ch in "0123456789abcdef" for ch in digest)
        and row.get("single_speaker") is not False
        and _number(row.get("ptbr_probability")) >= PTBR_REFERENCE_PROBABILITY_MIN
        and _number(row.get("clipping_ratio"), 1.0) <= CLIPPING_RATIO_MAX
        and _number(row.get("snr_db")) >= SNR_DB_MIN
        and _number(row.get("speech_ratio")) >= SPEECH_RATIO_MIN
        and _number(row.get("duration_seconds")) > 0.0
    )


def _duration_rank(duration_seconds: float) -> tuple[int, float]:
    if PREFERRED_REFERENCE_SECONDS_MIN <= duration_seconds <= PREFERRED_REFERENCE_SECONDS_MAX:
        return (0, abs(duration_seconds - PREFERRED_REFERENCE_SECONDS_TARGET))
    if duration_seconds > PREFERRED_REFERENCE_SECONDS_MAX:
        return (1, duration_seconds - PREFERRED_REFERENCE_SECONDS_MAX)
    return (2, PREFERRED_REFERENCE_SECONDS_MIN - duration_seconds)


def select_owner_reference(
    references: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    candidates = [dict(row) for row in references if _identity_grade(row)]
    if not candidates:
        raise ValueError("OWNER_REFERENCE_NO_IDENTITY_GRADE_CANDIDATE")

    def rank(row: Mapping[str, Any]) -> tuple[Any, ...]:
        duration = _number(row.get("duration_seconds"))
        duration_bucket, duration_distance = _duration_rank(duration)
        return (
            -_number(row.get("quality_score")),
            duration_bucket,
            duration_distance,
            -_number(row.get("snr_db")),
            str(row.get("sha256") or ""),
            int(row.get("telegram_input_id") or 0),
        )

    selected = min(candidates, key=rank)
    selected["selection_policy"] = "QUALITY_FIRST_DETERMINISTIC"
    selected["latest_input_wins"] = False
    return selected


def _reference_text(
    reference: Mapping[str, Any],
    explicit_reference_text: str | None,
) -> str:
    text = str(
        explicit_reference_text
        or reference.get("reference_text")
        or reference.get("transcript")
        or ""
    ).strip()
    if not text:
        raise ValueError("OWNER_REFERENCE_TRANSCRIPT_REQUIRED")
    return text


def build_ptbr_clone_request(
    *,
    reference: Mapping[str, Any],
    text: str,
    seed: int = 424242,
    reference_text: str | None = None,
) -> dict[str, Any]:
    private_ref = str(reference.get("private_audio_ref") or "").strip()
    if not private_ref.startswith(f"private://voice/{VOICE_IDENTITY_ID}/"):
        raise ValueError("OWNER_TELEGRAM_REFERENCE_REQUIRED")
    if not _identity_grade(reference):
        raise ValueError("OWNER_IDENTITY_GRADE_REFERENCE_REQUIRED")

    target_text = " ".join(str(text or "").split()).strip()
    if not target_text:
        raise ValueError("OWNER_CLONE_TEXT_REQUIRED")

    ref_text = _reference_text(reference, reference_text)
    return {
        "schema": "OwnerVoiceQwenCloneRequest/v2",
        "voice_identity_id": VOICE_IDENTITY_ID,
        "reference_source": REFERENCE_SOURCE,
        "private_audio_ref": private_ref,
        "reference_sha256": str(reference["sha256"]).lower(),
        "reference_telegram_input_id": int(reference["telegram_input_id"]),
        "ref_audio_path": str(reference["runtime_path"]),
        "ref_text": ref_text,
        "text": target_text,
        "locale": EXTERNAL_LOCALE,
        "language": "Portuguese",
        "model_id": QWEN_OWNER_MODEL_ID,
        "model_revision": QWEN_OWNER_MODEL_REVISION,
        "qwen_tts_version": QWEN_TTS_VERSION,
        "clone_mode": QWEN_CLONE_MODE,
        "x_vector_only_mode": False,
        "one_candidate_only": True,
        "seed": int(seed),
        "generation_config": dict(QWEN_GENERATION_CONFIG),
        "provider_preset_voice_allowed": False,
        "provider_default_voice_allowed": False,
        "generic_voice_fallback": False,
        "alternate_voice_identity_allowed": False,
        "human_voice_identity_review_required": True,
        "human_ptbr_accent_review_required": True,
    }


def build_ptbr_audition_variants(
    *,
    reference: Mapping[str, Any],
    text: str,
    reference_text: str | None = None,
) -> list[dict[str, Any]]:
    """Backward-compatible name; the governed policy returns exactly one candidate."""
    return [
        build_ptbr_clone_request(
            reference=reference,
            text=text,
            reference_text=reference_text,
            seed=424242,
        )
    ]
