"""Pure logic: segment Luiz's own long (>30 s) reference clips for the ASR-only survey.

Owner decision (19/10 07:33 BRT): his sent audios already contain correct GTA
name pronunciations; segment the long clips instead of recording new ones.

Cuts happen only inside inter-word gaps (ASR word timestamps) that the energy
VAD also confirms as silence, so no word is ever cut. Each segment re-uses the
SAME survey filters (evaluate_reference_quality) and window identity check; no
BR_OWNER_V1 identity gate or threshold is touched. The public report carries
scalar metrics and term time spans only: never audio, embeddings, transcripts
or private paths.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Mapping, Sequence

from app.services.owner_voice_ptbr_narration_gate_service import TERM_RULE_ID
from app.services.owner_voice_reference_asr_survey_service import (
    SURVEY_TERMS,
    canonical_term_hits,
    evaluate_reference_quality,
    rank_distinct_references,
)

SEGMENT_REPORT_SCHEMA = "OwnerVoiceReferenceSegmentSurvey/v1"
LONG_CLIP_SECONDS = 30.0          # = survey MAX_DURATION_SECONDS (rejection reason)
MIN_SEGMENT_SECONDS = 6.0
MAX_SEGMENT_SECONDS = 25.0
MIN_CUT_GAP_SECONDS = 0.20        # inter-word gap required for a cut
MIN_CUT_SILENCE_SECONDS = 0.10    # contiguous energy-VAD silence inside that gap
EDGE_PAD_SECONDS = 0.15           # breathing room around first/last word
OWNER_ASSERTION = "OWNER_20261019_0733_AUDIOS_CONTAIN_CORRECT_GTA_PRONUNCIATIONS"

_PUBLIC_KEYS = (
    "segment_id", "source_reference_id", "source_telegram_message_id", "segment_sha256",
    "start", "end", "duration_seconds", "snr_db", "clipping_ratio", "vad_speech_ratio",
    "ptbr_probability", "language", "centroid_similarity", "window_identity_p10",
)


def _fold_tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9' ]+", " ", t).split()


def unique_by_sha(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Keep the first clip per exact sha256 (ordered by message id, then id)."""
    kept: list[dict[str, Any]] = []
    first: dict[str, str] = {}
    dups: dict[str, str] = {}
    order = sorted(rows, key=lambda r: (int(r.get("telegram_message_id") or 0), int(str(r["reference_id"])) if str(r["reference_id"]).isdigit() else 0, str(r["reference_id"])))
    for r in order:
        sha, rid = str(r["sha256"]), str(r["reference_id"])
        if sha in first:
            dups[rid] = first[sha]
            continue
        first[sha] = rid
        kept.append(dict(r))
    return kept, dups


def silence_cut_points(
    words: Sequence[Mapping[str, Any]], speech_mask: Sequence[bool], *, frame_s: float = 0.02,
    min_gap_s: float = MIN_CUT_GAP_SECONDS, min_silence_s: float = MIN_CUT_SILENCE_SECONDS,
) -> list[dict[str, float]]:
    """Cut candidates: centre of the longest VAD-silent run inside an inter-word gap."""
    mask = list(bool(v) for v in speech_mask)
    cuts: list[dict[str, float]] = []
    ws = sorted(words, key=lambda w: float(w["start"]))
    for a, b in zip(ws, ws[1:]):
        g0, g1 = float(a["end"]), float(b["start"])
        if g1 - g0 < min_gap_s:
            continue
        f0, f1 = int(-(-g0 // frame_s)), int(g1 // frame_s)  # frames fully inside the gap
        best, run_start, best_span = 0, None, None
        for f in range(f0, f1):
            silent = f < len(mask) and not mask[f]
            if silent and run_start is None:
                run_start = f
            if (not silent or f == f1 - 1) and run_start is not None:
                end = f + 1 if silent else f
                if end - run_start > best:
                    best, best_span = end - run_start, (run_start, end)
                run_start = None
        if best_span and best * frame_s >= min_silence_s - 1e-9:
            t = (best_span[0] + best_span[1]) * frame_s / 2.0
            t = min(max(t, g0), g1)
            cuts.append({"time": round(t, 3), "gap_seconds": round(g1 - g0, 3)})
    return cuts


def _span(words: Sequence[Mapping[str, Any]], lo: float, hi: float, total: float):
    inside = [w for w in words if float(w["start"]) >= lo and float(w["end"]) <= hi]
    if not inside:
        return None
    start = max(lo, float(inside[0]["start"]) - EDGE_PAD_SECONDS, 0.0)
    end = min(hi, float(inside[-1]["end"]) + EDGE_PAD_SECONDS, total)
    return start, end, len(inside)


def plan_segments(
    words: Sequence[Mapping[str, Any]], cuts: Sequence[Mapping[str, float]], total_seconds: float,
    *, min_s: float = MIN_SEGMENT_SECONDS, max_s: float = MAX_SEGMENT_SECONDS,
) -> list[dict[str, float]]:
    """Choose non-overlapping segments between silence boundaries maximising covered speech.

    Boundaries are the clip head/tail plus verified silence cuts, so a segment can
    never start or end inside a word. Regions that cannot form a 6-25 s segment
    are dropped (never forced through a word).
    """
    ws = sorted(words, key=lambda w: float(w["start"]))
    if not ws:
        return []
    total = float(total_seconds)
    bounds = sorted({0.0, *(float(c["time"]) for c in cuts), total})
    n = len(bounds)
    best: list[tuple[float, int, list[tuple[float, float]]]] = [(0.0, 0, [])] + [(-1.0, 0, [])] * (n - 1)
    for j in range(1, n):
        cand = (best[j - 1][0], best[j - 1][1], best[j - 1][2])  # skip region (j-1, j)
        for i in range(j):
            if best[i][0] < 0:
                continue
            sp = _span(ws, bounds[i], bounds[j], total)
            if not sp:
                continue
            s, e, _ = sp
            if not (min_s <= e - s <= max_s):
                continue
            score = best[i][0] + (e - s)
            nseg = best[i][1] + 1
            if score > cand[0] + 1e-9 or (abs(score - cand[0]) <= 1e-9 and nseg < cand[1]):
                cand = (score, nseg, best[i][2] + [(s, e)])
        best[j] = cand
    return [{"start": round(s, 3), "end": round(e, 3)} for s, e in best[-1][2]]


def term_occurrences(words: Sequence[Mapping[str, Any]], *, segment_start: float = 0.0) -> list[dict[str, Any]]:
    """Owner occurrences of canonical GTA terms with word-level time spans (segment-relative)."""
    toks: list[tuple[str, int]] = []
    ws = list(words)
    for i, w in enumerate(ws):
        for tok in _fold_tokens(w.get("word", "")):
            toks.append((tok, i))
    seq = [t for t, _ in toks]
    out: list[dict[str, Any]] = []
    for term in SURVEY_TERMS:
        tt = _fold_tokens(term)
        if not tt:
            continue
        for k in range(len(seq) - len(tt) + 1):
            if seq[k:k + len(tt)] == tt:
                a, b = ws[toks[k][1]], ws[toks[k + len(tt) - 1][1]]
                out.append({"term": term,
                            "start": round(float(a["start"]) - segment_start, 3),
                            "end": round(float(b["end"]) - segment_start, 3)})
    return sorted(out, key=lambda o: (o["start"], o["term"]))


def build_term_reference_index(segments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """term -> Luiz's own occurrences (segment id + word time span) for the PT-BR pro gate.

    Coverage with 1 qualified occurrence is usable but flagged weaker; whether the
    gate requires 1 or 2 occurrences per term is an OWNER decision (not applied).
    """
    terms: dict[str, dict[str, Any]] = {}
    for seg in segments:
        for occ in seg.get("term_occurrences") or ():
            row = terms.setdefault(str(occ["term"]), {"occurrences": [], "qualified_occurrences": 0, "unqualified_occurrences": 0})
            if seg.get("quality_passed") is True:
                row["qualified_occurrences"] += 1
                row["occurrences"].append({"segment_id": str(seg["segment_id"]),
                                           "start": float(occ["start"]), "end": float(occ["end"])})
            else:
                row["unqualified_occurrences"] += 1
    for row in terms.values():
        q = row["qualified_occurrences"]
        row["coverage"] = ("COVERED_MIN2" if q >= 2 else "COVERED_MIN1_REQUIRES_OWNER_EAR_GE4" if q == 1
                           else "NOT_COVERED_BY_QUALIFIED_SEGMENT")
        row["weaker_single_occurrence"] = q == 1
    return {
        "owner_assertion": OWNER_ASSERTION,
        "terms": dict(sorted(terms.items())),
        "canonical_terms_without_owner_occurrence": sorted(set(SURVEY_TERMS) - set(terms)),
        "min_occurrences_options": [1, 2],
        "proposed_rule": TERM_RULE_ID,
        "proposed_rule_text": "2 = covered; 1 = covered only with owner ear rating >= 4 (pronuncia_nomes_gta); 0 = uncovered",
        "min_occurrences_decision": "PENDING_OWNER_DECISION",
        "min_occurrences_applied": None,
    }


def build_segment_public_report(
    segments: Sequence[Mapping[str, Any]], *, duplicates: Mapping[str, tuple[str, str]],
    source_summary: Mapping[str, Any], run_meta: Mapping[str, Any],
) -> dict[str, Any]:
    rows = []
    for s in segments:
        r = dict(s)
        r.setdefault("reference_id", s["segment_id"])
        r["quality_reasons"] = list(evaluate_reference_quality(r))
        r["quality_passed"] = not r["quality_reasons"]
        rows.append(r)
    ranked = rank_distinct_references([r for r in rows if r["quality_passed"]])
    rejected = [r for r in rows if not r["quality_passed"]]

    def public(r: Mapping[str, Any]) -> dict[str, Any]:
        e = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k in _PUBLIC_KEYS}
        text = str(r.get("transcript") or "")
        words = len(_fold_tokens(text))
        e["transcript_sha256"] = hashlib.sha256(" ".join(_fold_tokens(text)).encode("utf-8")).hexdigest()
        e["word_count"] = words
        dur = float(r.get("duration_seconds") or 0.0)
        e["words_per_second"] = round(words / dur, 3) if dur > 0 else 0.0
        e["canonical_term_hits"] = canonical_term_hits(text)
        e["term_occurrences"] = [{"term": str(o["term"]), "start": float(o["start"]), "end": float(o["end"])}
                                 for o in r.get("term_occurrences") or ()]
        e["quality_reasons"] = list(r["quality_reasons"])
        e["quality_passed"] = bool(r["quality_passed"])
        if "distinctness" in r:
            e["distinctness"] = r["distinctness"]
        return e

    pub_ranked = [public(r) for r in ranked]
    for i, e in enumerate(pub_ranked, 1):
        e["rank"] = i
    pub_rejected = [public(r) for r in rejected]
    tally: dict[str, int] = {}
    for e in pub_rejected:
        for reason in e["quality_reasons"]:
            tally[reason] = tally.get(reason, 0) + 1
    return {
        "schema": SEGMENT_REPORT_SCHEMA,
        "voice_identity_id": "BR_OWNER_V1",
        "segment_seconds": [MIN_SEGMENT_SECONDS, MAX_SEGMENT_SECONDS],
        "source_summary": dict(source_summary),
        "segment_count": len(rows),
        "segment_duplicates": {k: {"of": v[0], "reason": v[1]} for k, v in sorted(duplicates.items())},
        "quality_passed_count": len(pub_ranked),
        "ranked": pub_ranked,
        "rejected": pub_rejected,
        "rejection_tally": dict(sorted(tally.items())),
        "term_reference_index": build_term_reference_index(pub_ranked + pub_rejected),
        "biometric_material_included": False,
        "transcripts_included": False,
        "synthesis_performed": False,
        "telegram_messages_sent": 0,
        "selection_authority": "NONE_HUMAN_OWNER_REVIEW_REQUIRED",
        "thresholds_changed": False,
        "run": dict(run_meta),
    }
