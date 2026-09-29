from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping


def normalize_ptbr_text(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", str(text or "").casefold())
    without_marks = "".join(ch for ch in folded if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9]+", " ", without_marks)
    return [token for token in cleaned.split() if token]


def word_error_rate(expected: str, observed: str) -> float:
    reference = normalize_ptbr_text(expected)
    hypothesis = normalize_ptbr_text(observed)
    if not reference:
        raise ValueError("EXPECTED_TEXT_REQUIRED")
    previous = list(range(len(hypothesis) + 1))
    for row, ref_word in enumerate(reference, start=1):
        current = [row]
        for col, hyp_word in enumerate(hypothesis, start=1):
            substitution = previous[col - 1] + (ref_word != hyp_word)
            insertion = current[col - 1] + 1
            deletion = previous[col] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return round(previous[-1] / len(reference), 6)


def build_variant_qa(
    *,
    expected_text: str,
    observed_text: str,
    detected_language: str,
    language_probability: float,
    audio_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    language = str(detected_language or "").strip().lower().replace("_", "-")
    probability = max(0.0, min(1.0, float(language_probability)))
    wer = word_error_rate(expected_text, observed_text)
    clipping = float(audio_metrics.get("clipping_ratio") or 0.0)
    speech_ratio = float(audio_metrics.get("speech_ratio") or 0.0)
    issues: list[str] = []
    if language not in {"pt", "pt-br"} or probability < 0.90:
        issues.append("NON_PORTUGUESE_OUTPUT")
    if wer > 0.25:
        issues.append("HIGH_WORD_ERROR_RATE")
    if clipping > 0.01:
        issues.append("OUTPUT_CLIPPING")
    if speech_ratio < 0.55:
        issues.append("LOW_OUTPUT_SPEECH_RATIO")
    return {
        "status": "FAIL" if issues else "PASS",
        "issues": issues,
        "locale_gate": "PT_BR_REQUIRED",
        "detected_language": language,
        "language_probability": probability,
        "word_error_rate": wer,
        "clipping_ratio": clipping,
        "speech_ratio": speech_ratio,
        "human_brazilian_accent_review_required": True,
        "human_voice_identity_review_required": True,
    }
