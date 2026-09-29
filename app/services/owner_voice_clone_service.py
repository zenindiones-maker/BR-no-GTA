from __future__ import annotations

from typing import Any, Iterable, Mapping


VOICE_IDENTITY_ID = "BR_OWNER_V1"
REFERENCE_SOURCE = "TELEGRAM"
EXTERNAL_LOCALE = "pt-BR"
CHATTERBOX_LANGUAGE_ID = "pt"
CHATTERBOX_PTBR_MODEL_ID = "ResembleAI/Chatterbox-Multilingual-pt-br"
CHATTERBOX_PTBR_T3_SHA256 = (
    "074aaf65255eb9cb960288f7cc72e09d3b5008f6e0b14868c0d4e5b0bd7cbb6c"
)
CHATTERBOX_PTBR_S3GEN_SHA256 = (
    "4a46190f3dccc2230fbb3488a930bccc925862ee68f2662433dfcfe93ce6c2cb"
)
PREFERRED_REFERENCE_SECONDS_MIN = 6.0
PREFERRED_REFERENCE_SECONDS_MAX = 10.0
PREFERRED_REFERENCE_SECONDS_TARGET = 8.0
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


def build_ptbr_clone_request(
    *,
    reference: Mapping[str, Any],
    text: str,
    cfg_weight: float,
    seed: int,
) -> dict[str, Any]:
    private_ref = str(reference.get("private_audio_ref") or "").strip()
    if not private_ref.startswith(f"private://voice/{VOICE_IDENTITY_ID}/"):
        raise ValueError("OWNER_TELEGRAM_REFERENCE_REQUIRED")
    if not _identity_grade(reference):
        raise ValueError("OWNER_IDENTITY_GRADE_REFERENCE_REQUIRED")

    target_text = " ".join(str(text or "").split()).strip()
    if not target_text:
        raise ValueError("OWNER_CLONE_TEXT_REQUIRED")

    weight = float(cfg_weight)
    if not 0.0 <= weight <= 1.0:
        raise ValueError("OWNER_CLONE_CFG_WEIGHT_OUT_OF_RANGE")

    return {
        "schema": "OwnerVoicePtBrCloneRequest/v1",
        "voice_identity_id": VOICE_IDENTITY_ID,
        "reference_source": REFERENCE_SOURCE,
        "private_audio_ref": private_ref,
        "reference_sha256": str(reference["sha256"]).lower(),
        "reference_telegram_input_id": int(reference["telegram_input_id"]),
        "audio_prompt_path": str(reference["runtime_path"]),
        "text": target_text,
        "locale": EXTERNAL_LOCALE,
        "language_id": CHATTERBOX_LANGUAGE_ID,
        "model_id": CHATTERBOX_PTBR_MODEL_ID,
        "cfg_weight": weight,
        "exaggeration": 0.5,
        "temperature": 0.8,
        "seed": int(seed),
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
) -> list[dict[str, Any]]:
    return [
        build_ptbr_clone_request(
            reference=reference,
            text=text,
            cfg_weight=cfg_weight,
            seed=424242,
        )
        for cfg_weight in (0.0, 0.3, 0.5)
    ]
