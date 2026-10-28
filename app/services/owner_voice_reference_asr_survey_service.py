"""Pure logic for the ASR-only survey of BR_OWNER_V1 inlier reference clips.

Goal: find more *distinct* real owner clips (different content, clean audio,
consistent identity) for later human-reviewed reference selection. This module
never synthesizes audio, never sends Telegram messages and builds a public
report that excludes audio, speaker embeddings, transcripts and private paths.
Thresholds here are survey filters only; they do not change any BR_OWNER_V1
identity gate (see docs/policy/owner_authorizations.md).
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Any, Callable, Mapping, Sequence

from app.services.gta6_pronunciation_lexicon_service import GTA6_CANONICAL_PRONUNCIATION_TERMS

PUBLIC_REPORT_SCHEMA = "OwnerVoiceReferenceAsrSurvey/v1"
TELEGRAM_READ_ONLY_METHODS = frozenset({"getFile"})

MIN_DURATION_SECONDS = 3.0
MAX_DURATION_SECONDS = 30.0
MIN_SNR_DB = 15.0              # same as the existing clear_speech rule
MAX_CLIPPING_RATIO = 0.01      # same as the existing clear_speech rule
MIN_VAD_SPEECH_RATIO = 0.60
MIN_PTBR_PROBABILITY = 0.80
MIN_TRANSCRIPT_WORDS = 4
WORDS_PER_SECOND_RANGE = (0.5, 6.0)   # outside => ASR hallucination / music / silence
NEAR_DUP_EMBEDDING_COSINE = 0.97
NEAR_DUP_TRANSCRIPT_JACCARD = 0.80
RANK_IDENTITY_WEIGHT = 0.7
RANK_DISTINCT_WEIGHT = 0.3

SURVEY_TERMS = tuple(sorted(set(GTA6_CANONICAL_PRONUNCIATION_TERMS) | {"GTA", "Lucia", "Jason"}))
_PUBLIC_KEYS = (
    "reference_id", "telegram_message_id", "sha256", "duration_seconds", "snr_db",
    "clipping_ratio", "vad_speech_ratio", "ptbr_probability", "language",
    "centroid_similarity", "window_identity_p10",
)


def readonly_telegram_api_call(base: Callable[[str, str, dict[str, Any]], Any]):
    """Wrap a Telegram Bot API caller so only file *reads* (getFile) are possible."""
    def call(token: str, method: str, payload: dict[str, Any]) -> Any:
        if method not in TELEGRAM_READ_ONLY_METHODS:
            raise PermissionError(f"TELEGRAM_METHOD_FORBIDDEN_IN_ASR_SURVEY:{method}")
        return base(token, method, payload)
    return call


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower())


def _tokens(text: str) -> set[str]:
    return set(_fold(text).split())


def transcript_jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0 or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def dedupe_references(
    rows: Sequence[Mapping[str, Any]], embeddings: Mapping[str, Sequence[float]],
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Drop exact (sha256) and near duplicates (same speaker embedding AND same words).

    Same-speaker clips naturally have high cosine; only cosine plus transcript
    overlap marks a re-sent/re-encoded copy of the same utterance.
    """
    kept: list[dict[str, Any]] = []
    duplicates: dict[str, tuple[str, str]] = {}
    by_sha: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: (int(r.get("telegram_message_id") or 0), str(r["reference_id"]))):
        rid = str(row["reference_id"]); sha = str(row["sha256"])
        if sha in by_sha:
            duplicates[rid] = (by_sha[sha], "SHA256_EXACT"); continue
        match = None
        for prev in kept:
            pid = str(prev["reference_id"])
            if (
                _cosine(embeddings.get(rid, ()), embeddings.get(pid, ())) >= NEAR_DUP_EMBEDDING_COSINE
                and transcript_jaccard(row.get("transcript", ""), prev.get("transcript", "")) >= NEAR_DUP_TRANSCRIPT_JACCARD
            ):
                match = pid; break
        if match:
            duplicates[rid] = (match, "EMBEDDING_AND_TRANSCRIPT_NEAR_DUPLICATE"); continue
        by_sha[sha] = rid
        kept.append(dict(row))
    return kept, duplicates


def evaluate_reference_quality(row: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    duration = float(row.get("duration_seconds") or 0.0)
    words = len(_fold(row.get("transcript", "")).split())
    if not MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
        reasons.append("DURATION_OUT_OF_RANGE")
    if float(row.get("snr_db") or 0.0) < MIN_SNR_DB:
        reasons.append("SNR_BELOW_15DB")
    if float(row.get("clipping_ratio") or 0.0) > MAX_CLIPPING_RATIO:
        reasons.append("CLIPPING_ABOVE_1PCT")
    if float(row.get("vad_speech_ratio") or 0.0) < MIN_VAD_SPEECH_RATIO:
        reasons.append("VAD_SPEECH_RATIO_BELOW_0.60")
    if float(row.get("ptbr_probability") or 0.0) < MIN_PTBR_PROBABILITY:
        reasons.append("PTBR_PROBABILITY_BELOW_0.80")
    if words < MIN_TRANSCRIPT_WORDS:
        reasons.append("TRANSCRIPT_TOO_SHORT")
    elif duration > 0:
        wps = words / duration
        if not WORDS_PER_SECOND_RANGE[0] <= wps <= WORDS_PER_SECOND_RANGE[1]:
            reasons.append("SPEECH_RATE_IMPLAUSIBLE")
    if row.get("window_consistent") is not True:
        reasons.append("WINDOW_IDENTITY_INCONSISTENT")
    return tuple(reasons)


def rank_distinct_references(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Greedy MMR: identity (centroid similarity) first, then content distinctness."""
    pool = [dict(r) for r in rows]
    ranked: list[dict[str, Any]] = []
    while pool:
        def score(r: Mapping[str, Any]) -> tuple[float, str]:
            overlap = max((transcript_jaccard(r.get("transcript", ""), s.get("transcript", "")) for s in ranked), default=0.0)
            value = RANK_IDENTITY_WEIGHT * float(r.get("centroid_similarity") or 0.0) + RANK_DISTINCT_WEIGHT * (1.0 - overlap)
            return (value, str(r["reference_id"]))
        best = max(pool, key=score)
        best["distinctness"] = round(1.0 - max((transcript_jaccard(best.get("transcript", ""), s.get("transcript", "")) for s in ranked), default=0.0), 4)
        ranked.append(best); pool.remove(best)
    return ranked


def canonical_term_hits(transcript: str) -> list[str]:
    folded = f" {_fold(transcript)} "
    return sorted(t for t in SURVEY_TERMS if f" {_fold(t).strip()} " in folded)


def build_public_report(
    rows: Sequence[Mapping[str, Any]], *, duplicates: Mapping[str, tuple[str, str]],
    inlier_count: int, run_meta: Mapping[str, Any],
) -> dict[str, Any]:
    entries = []
    for row in rows:
        entry = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items() if k in _PUBLIC_KEYS}
        text = str(row.get("transcript") or "")
        entry["transcript_sha256"] = hashlib.sha256(_fold(text).strip().encode("utf-8")).hexdigest()
        entry["word_count"] = len(_fold(text).split())
        entry["canonical_term_hits"] = canonical_term_hits(text)
        entry["quality_reasons"] = list(evaluate_reference_quality(row))
        entry["quality_passed"] = not entry["quality_reasons"]
        if "distinctness" in row:
            entry["distinctness"] = row["distinctness"]
        entries.append(entry)
    passed = [e for e in entries if e["quality_passed"]]
    for i, e in enumerate(passed, 1):
        e["rank"] = i
    return {
        "schema": PUBLIC_REPORT_SCHEMA,
        "voice_identity_id": "BR_OWNER_V1",
        "inlier_count": int(inlier_count),
        "deduplicated_count": len(entries),
        "duplicates": {k: {"of": v[0], "reason": v[1]} for k, v in sorted(duplicates.items())},
        "quality_passed_count": len(passed),
        "ranked": passed,
        "rejected": [e for e in entries if not e["quality_passed"]],
        "biometric_material_included": False,
        "transcripts_included": False,
        "synthesis_performed": False,
        "telegram_messages_sent": 0,
        "selection_authority": "NONE_HUMAN_OWNER_REVIEW_REQUIRED",
        "run": dict(run_meta),
    }
