from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

TARGET_MIN_SECONDS = 20 * 60
TARGET_PREFERRED_MAX_SECONDS = 25 * 60
# Rejected VIDEO A measured 166.28081098469863 WPM at locked +0% Voice B.
# Plan at 170 WPM so editorial sufficiency cannot pass by assuming a slower
# speech rate than the human-approved runtime actually delivers.
VOICE_B_CONTENT_PLANNING_WPM = 170.0
VOICE_B_REJECTED_OBSERVED_WPM = 166.28081098469863
MIN_UNIQUE_MEDIA_ASSETS = 4
MAX_SINGLE_ASSET_SHARE = 0.45
MAX_PREVIOUS_MEDIA_REUSE_RATIO = 0.25
PRONUNCIATION_LEXICON_PATH = Path(__file__).resolve().parents[2] / "config" / "pronunciation_lexicon.json"
PRONUNCIATION_HUMAN_APPROVALS_PATH = Path(__file__).resolve().parents[2] / "config" / "pronunciation_human_approvals.json"

_STRUCTURAL = {
    "hook", "introdução", "introducao", "intro", "contexto", "desenvolvimento",
    "conclusão", "conclusao", "cta", "body", "opening", "closing",
    "official fact", "official statement", "analysis", "not confirmed",
    "confirmado", "declaração oficial", "declaracao oficial", "análise", "analise",
    "não confirmado", "nao confirmado", "informação atual de loja",
}
_DEBUG = {"debug", "scene", "section", "segment", "editplan", "timeline", "metadata"}
_TRANSCRIPT_TRACKS = {"CAPTIONS", "BRAND_CAPTIONS", "TRANSCRIPT", "SUBTITLES"}


def _norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-zà-ÿ0-9]+", str(value or "").casefold()))


def validate_text_overlay_contract(
    *,
    texts: Iterable[Any],
    planned_text_overlays: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    planned = {
        (_norm(item.get("text")), str(item.get("track") or "").strip())
        for item in planned_text_overlays
        if isinstance(item, dict) and _norm(item.get("text"))
    }
    unplanned: list[dict[str, str]] = []
    structural: list[str] = []
    debug: list[str] = []
    transcript: list[str] = []
    for raw in texts:
        text = str(getattr(raw, "text", "") if not isinstance(raw, dict) else raw.get("text") or "").strip()
        track = str(getattr(raw, "track", "") if not isinstance(raw, dict) else raw.get("track") or "").strip()
        normalized = _norm(text)
        if not normalized:
            continue
        if (normalized, track) not in planned:
            unplanned.append({"text": text, "track": track})
        if normalized in _STRUCTURAL or any(normalized.startswith(prefix + " ") for prefix in _STRUCTURAL):
            structural.append(text)
        if any(token in normalized.split() for token in _DEBUG):
            debug.append(text)
        if track.upper() in _TRANSCRIPT_TRACKS:
            transcript.append(text)
    return {
        "status": "PASS" if not unplanned and not structural and not debug and not transcript else "FAIL",
        "STRUCTURAL_LABEL_OVERLAY": "OFF" if not structural else "ON",
        "DEBUG_OVERLAY": "OFF" if not debug else "ON",
        "BURNED_SUBTITLES": "OFF" if not transcript else "ON",
        "OPEN_CAPTIONS": "OFF" if not transcript else "ON",
        "TRANSCRIPT_OVERLAY": "OFF" if not transcript else "ON",
        "UNPLANNED_TEXT_OVERLAY": "OFF" if not unplanned else "ON",
        "unplanned": unplanned,
        "structural": structural,
        "debug": debug,
        "transcript": transcript,
    }


def validate_content_duration(
    *,
    target_duration_seconds: float,
    content_supported_duration_seconds: float,
    artificial_padding: bool,
) -> dict[str, Any]:
    target = float(target_duration_seconds)
    supported = float(content_supported_duration_seconds)
    finite = math.isfinite(target) and math.isfinite(supported)
    target_in_band = finite and TARGET_MIN_SECONDS <= target <= TARGET_PREFERRED_MAX_SECONDS
    content_supports_target = finite and supported >= target
    status = (
        target_in_band
        and supported >= TARGET_MIN_SECONDS
        and content_supports_target
        and not artificial_padding
    )
    return {
        "status": "PASS" if status else "FAIL",
        "TARGET_DURATION_MINUTES": target / 60.0 if math.isfinite(target) else None,
        "CONTENT_SUPPORTED_DURATION": supported / 60.0 if math.isfinite(supported) else None,
        "TARGET_DURATION_MINUTES_GTE_20": bool(finite and target >= TARGET_MIN_SECONDS),
        "TARGET_DURATION_WITHIN_20_25": bool(target_in_band),
        "CONTENT_SUPPORTED_DURATION_GTE_20": bool(finite and supported >= TARGET_MIN_SECONDS),
        "CONTENT_SUPPORTS_TARGET": bool(content_supports_target),
        "ARTIFICIAL_PADDING": "ON" if artificial_padding else "OFF",
        "preferred_upper_bound_minutes": TARGET_PREFERRED_MAX_SECONDS / 60.0,
    }


def validate_media_novelty(
    *,
    semantic_links: Iterable[dict[str, Any]],
    previous_asset_refs: Iterable[str] = (),
) -> dict[str, Any]:
    links = [item for item in semantic_links if isinstance(item, dict)]
    durations: Counter[str] = Counter()
    total = 0.0
    for item in links:
        ref = str(item.get("asset_ref") or "").strip()
        if not ref:
            continue
        duration = float(item.get("duration_seconds") or 0.0)
        if not math.isfinite(duration) or duration <= 0:
            continue
        durations[ref] += duration
        total += duration
    previous = {str(item).strip() for item in previous_asset_refs if str(item).strip()}
    unique = set(durations)
    max_share = max((value / total for value in durations.values()), default=1.0)
    reused = unique & previous
    reused_duration = sum(durations[ref] for ref in reused)
    reuse_ratio = reused_duration / total if total > 0 else 1.0
    diversity_ok = len(unique) >= MIN_UNIQUE_MEDIA_ASSETS
    concentration_ok = max_share <= MAX_SINGLE_ASSET_SHARE
    reuse_ok = reuse_ratio <= MAX_PREVIOUS_MEDIA_REUSE_RATIO
    return {
        "status": "PASS" if total > 0 and diversity_ok and concentration_ok and reuse_ok else "FAIL",
        "MEDIA_NOVELTY": "PASS" if total > 0 and diversity_ok and concentration_ok and reuse_ok else "FAIL",
        "unique_asset_count": len(unique),
        "minimum_unique_asset_count": MIN_UNIQUE_MEDIA_ASSETS,
        "max_single_asset_share": round(max_share, 6),
        "max_single_asset_share_allowed": MAX_SINGLE_ASSET_SHARE,
        "previous_media_reuse_ratio": round(reuse_ratio, 6),
        "previous_media_reuse_ratio_allowed": MAX_PREVIOUS_MEDIA_REUSE_RATIO,
        "reused_asset_refs": sorted(reused),
        "asset_duration_seconds": dict(sorted(durations.items())),
    }


def validate_pronunciation_readiness(
    *,
    lexicon_path: Path | None = None,
    approvals_path: Path | None = None,
) -> dict[str, Any]:
    """Fail closed until Leonida has real human auditory approval.

    Written/canonical text remains Leonida. The synthesis-only alias Leônida is
    permitted only inside the pt-BR pronunciation layer and must never authorize
    production by its mere presence in the lexicon.
    """
    lexicon = json.loads((lexicon_path or PRONUNCIATION_LEXICON_PATH).read_text(encoding="utf-8"))
    approvals = json.loads((approvals_path or PRONUNCIATION_HUMAN_APPROVALS_PATH).read_text(encoding="utf-8"))
    entries = {
        str(item.get("identity") or ""): item
        for item in (lexicon.get("entries") or [])
        if isinstance(item, dict)
    }
    leonida = dict(entries.get("leonida") or {})
    alias_registered = (
        leonida.get("term") == "Leonida"
        and leonida.get("locale") == "pt-BR"
        and leonida.get("strategy") == "alias"
        and leonida.get("synthesis_text") == "Leônida"
        and leonida.get("critical") is True
    )
    term = dict(((approvals.get("terms") or {}).get("leonida") or {}))
    human_approved = (
        term.get("status") == "APPROVED"
        and term.get("auditory_review_required") is True
        and term.get("approved") is True
        and bool(term.get("proof_run_id"))
        and bool(term.get("telegram_message_ids"))
    )
    pronunciation_pass = alias_registered and human_approved
    return {
        "status": "PASS" if pronunciation_pass else "FAIL",
        "LEONIDA_ALIAS_REGISTERED": "PASS" if alias_registered else "FAIL",
        "LEONIDA_WRITTEN_FORM": "Leonida",
        "LEONIDA_SYNTHESIS_ALIAS": "Leônida",
        "LEONIDA_PRONUNCIATION": "PASS" if pronunciation_pass else "FAIL",
        "LEONIDA_HUMAN_AUDIO_REVIEW": "PASS" if human_approved else "PENDING",
        "DEFAULT_NARRATION_LOCALE": "pt-BR",
        "EDITORIAL_TEXT_MUTATED": "NO",
        "TRANSCRIPT_MUTATED": "NO",
        "SEO_TEXT_MUTATED": "NO",
        "CAPTION_TEXT_MUTATED": "NO",
        "PRODUCTION_READINESS": "PASS" if pronunciation_pass else "FAIL",
        "FULL_RENDER_AUTHORIZED": "YES" if pronunciation_pass else "NO",
        "human_approval_status": term.get("status") or "MISSING",
        "proof_run_id": term.get("proof_run_id"),
        "telegram_message_ids": list(term.get("telegram_message_ids") or []),
    }
