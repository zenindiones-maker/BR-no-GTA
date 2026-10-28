"""Orquestra o gate PT-BR de narração dentro do clone (aditivo, fail-closed)."""
from __future__ import annotations

import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services import owner_voice_ptbr_narration_features as F
from app.services.gta6_pronunciation_lexicon_service import GTA6_CANONICAL_PRONUNCIATION_TERMS
from app.services.owner_voice_human_audition_pack_service import character_error_rate, word_error_rate
from app.services.owner_voice_ptbr_narration_gate_service import (
    OWNER_RULE_ID,
    build_public_gate_report,
    calibrate_ptbr_narration_profile,
    evaluate_ptbr_narration_gate,
)

NARRATION_TERMS = tuple(sorted(set(GTA6_CANONICAL_PRONUNCIATION_TERMS) | {"GTA", "Lucia", "Jason"}))


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9']+", " ", t).strip() + " "


def narration_terms(text: str) -> list[str]:
    folded = _fold(text)
    return [t for t in NARRATION_TERMS if _fold(t) in folded]


def _master_for_measurement(source: Path, target: Path) -> Path:
    """Masteriza uma CÓPIA privada em -16 LUFS / TP -1.5 para provar que a voz
    atinge o padrão de entrega sem clipar (não altera o candidato)."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(target)],
        check=True, capture_output=True,
    )
    return target


def _clip_features(path: Path, dnsmos_model_path: Path, scorers: Any) -> dict[str, float]:
    row: dict[str, float] = {}
    row.update(F.dnsmos_p835(path, dnsmos_model_path))
    row["utmos"] = float(scorers.utmos(path))
    row["accent_ptbr_probability"] = float(scorers.accent_ptbr_probability(path))
    row.update(F.prosody_features(path))
    return row


def _repetitions(text: str) -> int:
    words = _fold(text).split()
    return sum(1 for a, b in zip(words, words[1:]) if a == b)


def run_ptbr_narration_gate(
    *,
    owner_clips: Mapping[str, tuple[Path, str]],
    candidate_wav16: Path,
    candidate_sha256: str,
    segment_qas: Sequence[Mapping[str, Any]],
    dnsmos_model_path: Path,
    scorers: Any,
    workspace: Path,
    term_phoneme_evidence: Mapping[str, Mapping[str, float]] | None = None,
    term_owner_occurrences: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    profile: dict[str, Any] = {"owner_clip_sha256s": [], "floors": {}, "bands": {}, "uppers": {}}
    try:
        owner_rows = []
        for _rid, (path, sha) in sorted(owner_clips.items()):
            row = _clip_features(Path(path), dnsmos_model_path, scorers)
            row["sha256"] = sha
            owner_rows.append(row)
        profile = calibrate_ptbr_narration_profile(owner_rows)

        cand: dict[str, Any] = {"audio_sha256": candidate_sha256}
        cand.update(_clip_features(candidate_wav16, dnsmos_model_path, scorers))
        cand["clipping_ratio"] = F.clipping_ratio(candidate_wav16)
        master = _master_for_measurement(candidate_wav16, Path(workspace) / "ptbr-gate-master-48k.wav")
        cand.update(F.ebur128_loudness(master))

        expected = " ".join(str(q.get("expected_text") or "") for q in segment_qas).strip()
        observed = " ".join(str(q.get("observed_text") or "") for q in segment_qas).strip()
        languages = {str(q.get("language") or "").lower() for q in segment_qas}
        cand["language"] = "pt" if languages and languages <= {"pt", "pt-br"} else ",".join(sorted(languages)) or "unknown"
        probs = [float(q.get("language_probability") or 0.0) for q in segment_qas]
        cand["language_probability"] = min(probs) if probs else None
        cand["asr_word_error_rate"] = word_error_rate(expected, observed) if expected else None
        cand["asr_character_error_rate"] = character_error_rate(expected, observed) if expected else None
        cers = [float(q["character_error_rate"]) for q in segment_qas if q.get("character_error_rate") is not None]
        cand["asr_segment_character_error_rate_max"] = max(cers) if cers else None
        cand["adjacent_repetition_count"] = _repetitions(observed)

        evidence = dict(term_phoneme_evidence or {})
        folded_observed = _fold(observed)
        cand["terms"] = [
            {
                "term": term,
                "asr_recognized": _fold(term) in folded_observed,
                "phoneme_error_rate": (evidence.get(term) or {}).get("phoneme_error_rate"),
                "owner_reference_bound": (evidence.get(term) or {}).get("owner_reference_bound"),
                # Ocorrências reais do Luiz (índice do segment survey); ausente = regra antiga.
                **({"owner_occurrences": int(term_owner_occurrences.get(term, 0))}
                   if term_owner_occurrences is not None else {}),
            }
            for term in narration_terms(expected)
        ]
        result = evaluate_ptbr_narration_gate(cand, profile)
    except Exception as exc:  # fail-closed: qualquer falha de extração bloqueia
        result = {
            "schema": "OwnerVoicePtbrNarrationGate/v1", "owner_rule_id": OWNER_RULE_ID, "passed": False,
            "fail_reasons": [f"PTBR_GATE_EXTRACTION_ERROR:{type(exc).__name__}:{str(exc)[:160]}"],
            "metrics": {}, "terms": [], "additive_only": True,
        }
    return {"result": result, "report": build_public_gate_report(result, profile)}
