"""Gate aditivo e fail-closed de narração PT-BR ultra profissional (BR_OWNER_V1).

Regra do dono (OWNER_RULE_20261019_PTBR_ULTRA_PROFESSIONAL_NARRATION, ver
docs/policy/owner_authorizations.md): "Se a voz não estiver com qualidade
Português BR ultra profissional não será aprovada."

Princípios:
- ADITIVO: só pode bloquear. Nunca reduz/substitui os gates de identidade
  (centroide 0.868594, p10 por segmento, referência) nem a aprovação humana.
- Limiares vêm (a) das gravações reais do Luiz (p10 / banda p05–p95, mesma
  extração aplicada aos dois lados) ou (b) de referências documentadas
  (docs/architecture/br-owner-ptbr-narration-gate-v1.md). Nunca do candidato.
- Pisos documentados nunca são rebaixados pela calibração do dono.
- Métrica ausente = FALHA. O ouvido do Luiz continua sendo a autoridade final.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

GATE_SCHEMA = "OwnerVoicePtbrNarrationGate/v1"
OWNER_RULE_ID = "OWNER_RULE_20261019_PTBR_ULTRA_PROFESSIONAL_NARRATION"
MIN_OWNER_CALIBRATION_CLIPS = 8

# Regra PROPOSTA de cobertura dos termos do GTA (19/10/2026), pendente de
# confirmação do Luiz: 2 ocorrências reais dele = coberto (limite fonêmico p90);
# 1 ocorrência = coberto só com nota de ouvido do Luiz >= 4 em
# 'pronuncia_nomes_gta'; 0 = descoberto. Enquanto não confirmada, 1 ocorrência
# FALHA (fail-closed; nada fica mais frouxo que antes).
TERM_RULE_ID = "PROPOSED_TERM_RULE_20261019_MIN2_OR_1_WITH_OWNER_EAR_GE4"
TERM_RULE_OWNER_CONFIRMED = False
TERM_RULE_MIN_OCCURRENCES = 2
TERM_RULE_SINGLE_OCCURRENCE_EAR_MIN = 4

# Referências documentadas (fontes no doc de arquitetura). Não ajustar para
# aprovar candidato; mudanças exigem autorização explícita do dono.
DOCUMENTED_LIMITS: dict[str, float] = {
    # Whisper large-v3 em fala lida PT (FLEURS) ~3.5–3.8% WER; 0.08 ≈ 2x humano.
    "asr_wer_max": 0.08,
    "asr_cer_max": 0.03,
    "asr_segment_cer_max": 0.06,
    "language_probability_min": 0.90,
    # Classificador pt-BR vs pt-PT (lgris/portuguese-accent-classifier, ~95% acc).
    "accent_ptbr_probability_min": 0.80,
    # Master de narração: -16 LUFS ±1 (YouTube normaliza em -14, não amplifica);
    # true peak <= -1 dBTP (YouTube/streaming).
    "loudness_target_lufs": -16.0,
    "loudness_tolerance_lu": 1.0,
    "true_peak_max_dbtp": -1.0,
    "clipping_ratio_max": 0.0005,
    "adjacent_repetition_max": 0,
}

# Métricas "quanto maior melhor": piso = p10 das gravações do Luiz.
OWNER_FLOOR_METRICS = ("dnsmos_sig", "dnsmos_ovrl", "utmos", "accent_ptbr_probability")
# Métricas de prosódia: candidato dentro da banda p05–p95 do Luiz.
OWNER_BAND_METRICS = ("speech_rate_syllables_per_second", "f0_std_semitones", "pause_ratio")
# Limite superior apenas.
OWNER_UPPER_METRICS = ("pause_p90_seconds",)

_REASON_FLOOR = {
    "dnsmos_sig": "DNSMOS_SIG_BELOW_OWNER_P10",
    "dnsmos_ovrl": "DNSMOS_OVRL_BELOW_OWNER_P10",
    "utmos": "UTMOS_BELOW_OWNER_P10",
    "accent_ptbr_probability": "ACCENT_PTBR_BELOW_FLOOR",
}
_REASON_BAND = {
    "speech_rate_syllables_per_second": "SPEECH_RATE_OUTSIDE_OWNER_BAND",
    "f0_std_semitones": "F0_VARIATION_OUTSIDE_OWNER_BAND",
    "pause_ratio": "PAUSE_RATIO_OUTSIDE_OWNER_BAND",
}
_SCALAR_KEYS = (
    "dnsmos_sig", "dnsmos_bak", "dnsmos_ovrl", "utmos", "accent_ptbr_probability",
    "speech_rate_syllables_per_second", "f0_std_semitones", "pause_ratio", "pause_p90_seconds",
    "language", "language_probability", "asr_word_error_rate", "asr_character_error_rate",
    "asr_segment_character_error_rate_max", "adjacent_repetition_count", "clipping_ratio",
    "integrated_loudness_lufs", "true_peak_dbtp", "audio_sha256",
)


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        raise ValueError("EMPTY_DISTRIBUTION")
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _finite(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def calibrate_ptbr_narration_profile(owner_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calibra limiares nas gravações reais do Luiz (inliers), mesma extração do candidato."""
    rows = [dict(r) for r in owner_rows]
    if len(rows) < MIN_OWNER_CALIBRATION_CLIPS:
        raise ValueError(f"OWNER_CALIBRATION_INSUFFICIENT:{len(rows)}<{MIN_OWNER_CALIBRATION_CLIPS}")
    def column(name: str) -> list[float]:
        values = [_finite(r.get(name)) for r in rows]
        clean = [v for v in values if v is not None]
        if len(clean) < MIN_OWNER_CALIBRATION_CLIPS:
            raise ValueError(f"OWNER_CALIBRATION_INSUFFICIENT:{name}")
        return clean
    floors = {m: round(_quantile(column(m), 0.10), 6) for m in OWNER_FLOOR_METRICS}
    floors["accent_ptbr_probability"] = max(
        floors["accent_ptbr_probability"], DOCUMENTED_LIMITS["accent_ptbr_probability_min"]
    )
    bands = {m: [round(_quantile(column(m), 0.05), 6), round(_quantile(column(m), 0.95), 6)] for m in OWNER_BAND_METRICS}
    uppers = {m: round(_quantile(column(m), 0.95), 6) for m in OWNER_UPPER_METRICS}
    shas = sorted(str(r.get("sha256") or "") for r in rows)
    fingerprint = hashlib.sha256(json.dumps(
        {"shas": shas, "floors": floors, "bands": bands, "uppers": uppers, "limits": DOCUMENTED_LIMITS},
        sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return {
        "source": "BR_OWNER_V1_REAL_RECORDINGS",
        "owner_clip_count": len(rows),
        "owner_clip_sha256s": shas,
        "floors": floors,
        "bands": bands,
        "uppers": uppers,
        "documented_limits": dict(DOCUMENTED_LIMITS),
        "calibration_sha256": fingerprint,
    }


def evaluate_ptbr_narration_gate(candidate: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    L = DOCUMENTED_LIMITS
    def get(name: str) -> float | None:
        v = _finite(candidate.get(name))
        if v is None:
            reasons.append(f"METRIC_UNAVAILABLE:{name}")
        return v

    if str(candidate.get("audio_sha256") or "") in set(profile.get("owner_clip_sha256s") or ()):
        reasons.append("CANDIDATE_IN_OWNER_CALIBRATION_SET")
    for m in OWNER_FLOOR_METRICS:
        v = get(m)
        if v is not None and v < float(profile["floors"][m]):
            reasons.append(_REASON_FLOOR[m])
    for m in OWNER_BAND_METRICS:
        v = get(m)
        lo, hi = profile["bands"][m]
        if v is not None and not float(lo) <= v <= float(hi):
            reasons.append(_REASON_BAND[m])
    v = get("pause_p90_seconds")
    if v is not None and v > float(profile["uppers"]["pause_p90_seconds"]):
        reasons.append("PAUSE_P90_ABOVE_OWNER_P95")

    language = str(candidate.get("language") or "").lower().replace("_", "-")
    if language not in {"pt", "pt-br"}:
        reasons.append("LANGUAGE_NOT_PORTUGUESE")
    v = get("language_probability")
    if v is not None and v < L["language_probability_min"]:
        reasons.append("LANGUAGE_PROBABILITY_BELOW_0.90")
    v = get("asr_word_error_rate")
    if v is not None and v > L["asr_wer_max"]:
        reasons.append("ASR_WER_ABOVE_0.08")
    v = get("asr_character_error_rate")
    if v is not None and v > L["asr_cer_max"]:
        reasons.append("ASR_CER_ABOVE_0.03")
    v = get("asr_segment_character_error_rate_max")
    if v is not None and v > L["asr_segment_cer_max"]:
        reasons.append("ASR_SEGMENT_CER_ABOVE_0.06")
    v = get("adjacent_repetition_count")
    if v is not None and v > L["adjacent_repetition_max"]:
        reasons.append("REPEATED_TOKENS")
    v = get("clipping_ratio")
    if v is not None and v > L["clipping_ratio_max"]:
        reasons.append("CLIPPING_ABOVE_0.0005")
    v = get("integrated_loudness_lufs")
    if v is not None and abs(v - L["loudness_target_lufs"]) > L["loudness_tolerance_lu"]:
        reasons.append("LOUDNESS_OUTSIDE_-16_PLUS_MINUS_1_LUFS")
    v = get("true_peak_dbtp")
    if v is not None and v > L["true_peak_max_dbtp"]:
        reasons.append("TRUE_PEAK_ABOVE_-1_DBTP")

    terms_out = []
    pending_ear: list[str] = []
    terms = candidate.get("terms")
    if not isinstance(terms, list):
        reasons.append("METRIC_UNAVAILABLE:terms")
        terms = []
    for row in terms:
        term = str(row.get("term") or "")
        status = "PASS"
        per = _finite(row.get("phoneme_error_rate"))
        bound = _finite(row.get("owner_reference_bound"))
        occ_raw = row.get("owner_occurrences")
        occ = None if occ_raw is None else int(occ_raw)
        coverage = None
        if row.get("asr_recognized") is not True:
            status = f"TERM_NOT_RECOGNIZED:{term}"
        elif occ is not None and occ <= 0:
            status, coverage = f"OWNER_TERM_UNCOVERED:{term}", "UNCOVERED"
        elif occ is not None and occ < TERM_RULE_MIN_OCCURRENCES:
            if TERM_RULE_OWNER_CONFIRMED:
                status, coverage = "PENDING_OWNER_EAR_RATING", "COVERED_MIN1_PENDING_OWNER_EAR"
                pending_ear.append(term)
            else:
                status = f"TERM_RULE_SINGLE_OCCURRENCE_PENDING_OWNER_CONFIRMATION:{term}"
                coverage = "SINGLE_OCCURRENCE_RULE_UNCONFIRMED"
        elif bound is None:
            status = f"OWNER_TERM_REFERENCE_MISSING:{term}"
        elif per is None:
            status = f"METRIC_UNAVAILABLE:phoneme_error_rate:{term}"
        elif per > bound:
            status = f"TERM_PHONEMES_OUTSIDE_OWNER_BOUND:{term}"
        if occ is not None and coverage is None and occ >= TERM_RULE_MIN_OCCURRENCES:
            coverage = "COVERED_MIN2"
        if status not in ("PASS", "PENDING_OWNER_EAR_RATING"):
            reasons.append(status)
        out_row = {"term": term, "status": status,
                   "phoneme_error_rate": None if per is None else round(per, 4),
                   "owner_reference_bound": None if bound is None else round(bound, 4)}
        if occ is not None:
            out_row.update({"owner_occurrences": occ, "coverage": coverage,
                            "weaker_single_occurrence": occ == 1})
        terms_out.append(out_row)

    metrics = {k: candidate.get(k) for k in _SCALAR_KEYS if k in candidate}
    return {
        "schema": GATE_SCHEMA,
        "owner_rule_id": OWNER_RULE_ID,
        "passed": not reasons,
        "fail_reasons": list(dict.fromkeys(reasons)),
        "metrics": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in metrics.items()},
        "terms": terms_out,
        "pending_owner_ear_terms": pending_ear,
        "term_rule": _term_rule(),
        "calibration_sha256": profile.get("calibration_sha256"),
        "additive_only": True,
    }


def _term_rule() -> dict[str, Any]:
    return {"id": TERM_RULE_ID, "owner_confirmed": bool(TERM_RULE_OWNER_CONFIRMED),
            "status": "OWNER_CONFIRMED" if TERM_RULE_OWNER_CONFIRMED else "PENDING_OWNER_CONFIRMATION",
            "min_occurrences": TERM_RULE_MIN_OCCURRENCES,
            "single_occurrence_requires_owner_ear_score": TERM_RULE_SINGLE_OCCURRENCE_EAR_MIN}


def combine_with_existing_delivery_gate(existing_eligible: bool, ptbr_result: Mapping[str, Any]) -> bool:
    """Elegibilidade final = gates existentes AND gate PT-BR. Nunca promove."""
    if not isinstance(ptbr_result, Mapping):
        raise TypeError("PTBR_GATE_RESULT_REQUIRED")
    return bool(existing_eligible) and ptbr_result.get("passed") is True


def build_public_gate_report(result: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": GATE_SCHEMA + "/report",
        "owner_rule_id": OWNER_RULE_ID,
        "passed": bool(result.get("passed")),
        "fail_reasons": list(result.get("fail_reasons") or ()),
        "metrics": dict(result.get("metrics") or {}),
        "terms": list(result.get("terms") or ()),
        "pending_owner_ear_terms": list(result.get("pending_owner_ear_terms") or ()),
        "term_rule": dict(result.get("term_rule") or _term_rule()),
        "calibration": {
            "source": profile.get("source"),
            "owner_clip_count": profile.get("owner_clip_count"),
            "floors": profile.get("floors"),
            "bands": profile.get("bands"),
            "uppers": profile.get("uppers"),
            "documented_limits": profile.get("documented_limits"),
            "calibration_sha256": profile.get("calibration_sha256"),
        },
        "biometric_material_included": False,
        "additive_only": True,
        "human_final_authority": "BR_OWNER_V1_LUIZ",
    }
