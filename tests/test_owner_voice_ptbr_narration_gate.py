"""Gate aditivo 'narração PT-BR ultra profissional' (regra do Luiz, 19/10/2026).

Fail-closed, calibrado nas gravações reais do Luiz e/ou referências
documentadas; nunca reduz nem substitui os gates de identidade existentes."""
from __future__ import annotations

import json

import pytest

from app.services.owner_voice_ptbr_narration_gate_service import (
    DOCUMENTED_LIMITS,
    GATE_SCHEMA,
    MIN_OWNER_CALIBRATION_CLIPS,
    build_public_gate_report,
    calibrate_ptbr_narration_profile,
    combine_with_existing_delivery_gate,
    evaluate_ptbr_narration_gate,
)


def _owner_rows(n=12):
    rows = []
    for i in range(n):
        rows.append({
            "sha256": f"{i:064x}",
            "dnsmos_sig": 3.3 + 0.02 * i, "dnsmos_ovrl": 2.9 + 0.02 * i,
            "utmos": 2.8 + 0.03 * i, "accent_ptbr_probability": 0.93 + 0.005 * i,
            "speech_rate_syllables_per_second": 4.6 + 0.08 * i,
            "f0_std_semitones": 2.6 + 0.1 * i, "pause_ratio": 0.12 + 0.01 * i,
            "pause_p90_seconds": 0.45 + 0.02 * i,
        })
    return rows


def _candidate(**over):
    c = {
        "audio_sha256": "f" * 64,
        "dnsmos_sig": 3.5, "dnsmos_ovrl": 3.1, "utmos": 3.0, "accent_ptbr_probability": 0.97,
        "speech_rate_syllables_per_second": 5.0, "f0_std_semitones": 3.1, "pause_ratio": 0.16,
        "pause_p90_seconds": 0.55, "language": "pt", "language_probability": 0.99,
        "asr_word_error_rate": 0.04, "asr_character_error_rate": 0.012,
        "asr_segment_character_error_rate_max": 0.03, "adjacent_repetition_count": 0,
        "clipping_ratio": 0.0, "integrated_loudness_lufs": -16.2, "true_peak_dbtp": -1.6,
        "terms": [{"term": "Vice City", "asr_recognized": True, "phoneme_error_rate": 0.10,
                   "owner_reference_bound": 0.20}],
    }
    c.update(over)
    return c


def test_calibration_uses_owner_recordings_only_and_is_fingerprinted():
    profile = calibrate_ptbr_narration_profile(_owner_rows())
    assert profile["source"] == "BR_OWNER_V1_REAL_RECORDINGS"
    assert profile["owner_clip_count"] == 12
    assert profile["floors"]["dnsmos_ovrl"] == pytest.approx(2.922, abs=1e-3)  # p10 do Luiz
    lo, hi = profile["bands"]["speech_rate_syllables_per_second"]
    assert lo == pytest.approx(4.644, abs=1e-3) and hi == pytest.approx(5.436, abs=1e-3)
    assert len(profile["calibration_sha256"]) == 64
    with pytest.raises(ValueError, match="OWNER_CALIBRATION_INSUFFICIENT"):
        calibrate_ptbr_narration_profile(_owner_rows(MIN_OWNER_CALIBRATION_CLIPS - 1))


def test_professional_candidate_passes():
    result = evaluate_ptbr_narration_gate(_candidate(), calibrate_ptbr_narration_profile(_owner_rows()))
    assert result["passed"] is True, result["fail_reasons"]
    assert result["schema"] == GATE_SCHEMA


@pytest.mark.parametrize("over,reason", [
    ({"dnsmos_ovrl": 2.5}, "DNSMOS_OVRL_BELOW_OWNER_P10"),
    ({"utmos": 2.0}, "UTMOS_BELOW_OWNER_P10"),
    ({"accent_ptbr_probability": 0.60}, "ACCENT_PTBR_BELOW_FLOOR"),
    ({"language": "en"}, "LANGUAGE_NOT_PORTUGUESE"),
    ({"asr_word_error_rate": 0.12}, "ASR_WER_ABOVE_0.08"),
    ({"asr_character_error_rate": 0.05}, "ASR_CER_ABOVE_0.03"),
    ({"asr_segment_character_error_rate_max": 0.09}, "ASR_SEGMENT_CER_ABOVE_0.06"),
    ({"speech_rate_syllables_per_second": 6.4}, "SPEECH_RATE_OUTSIDE_OWNER_BAND"),
    ({"f0_std_semitones": 1.2}, "F0_VARIATION_OUTSIDE_OWNER_BAND"),
    ({"pause_p90_seconds": 1.6}, "PAUSE_P90_ABOVE_OWNER_P95"),
    ({"adjacent_repetition_count": 1}, "REPEATED_TOKENS"),
    ({"clipping_ratio": 0.002}, "CLIPPING_ABOVE_0.0005"),
    ({"integrated_loudness_lufs": -19.5}, "LOUDNESS_OUTSIDE_-16_PLUS_MINUS_1_LUFS"),
    ({"true_peak_dbtp": -0.3}, "TRUE_PEAK_ABOVE_-1_DBTP"),
    ({"terms": [{"term": "Lucia", "asr_recognized": False, "phoneme_error_rate": 0.1, "owner_reference_bound": 0.2}]}, "TERM_NOT_RECOGNIZED:Lucia"),
    ({"terms": [{"term": "Lucia", "asr_recognized": True, "phoneme_error_rate": 0.1, "owner_reference_bound": None}]}, "OWNER_TERM_REFERENCE_MISSING:Lucia"),
    ({"terms": [{"term": "Lucia", "asr_recognized": True, "phoneme_error_rate": 0.4, "owner_reference_bound": 0.2}]}, "TERM_PHONEMES_OUTSIDE_OWNER_BOUND:Lucia"),
])
def test_each_dimension_fails_closed(over, reason):
    result = evaluate_ptbr_narration_gate(_candidate(**over), calibrate_ptbr_narration_profile(_owner_rows()))
    assert result["passed"] is False
    assert reason in result["fail_reasons"]


def test_missing_metric_is_a_failure_not_a_pass():
    cand = _candidate(); cand.pop("utmos")
    result = evaluate_ptbr_narration_gate(cand, calibrate_ptbr_narration_profile(_owner_rows()))
    assert result["passed"] is False and "METRIC_UNAVAILABLE:utmos" in result["fail_reasons"]


def test_candidate_cannot_be_part_of_its_own_calibration():
    rows = _owner_rows(); rows[0]["sha256"] = "f" * 64
    result = evaluate_ptbr_narration_gate(_candidate(), calibrate_ptbr_narration_profile(rows))
    assert "CANDIDATE_IN_OWNER_CALIBRATION_SET" in result["fail_reasons"]


def test_documented_floors_are_never_lowered_by_owner_calibration():
    rows = _owner_rows()
    for r in rows:
        r["accent_ptbr_probability"] = 0.55  # gravações ruins não rebaixam o piso documentado
    profile = calibrate_ptbr_narration_profile(rows)
    assert profile["floors"]["accent_ptbr_probability"] == DOCUMENTED_LIMITS["accent_ptbr_probability_min"]


def test_gate_is_additive_never_overrides_existing_gates():
    passing = {"passed": True}
    failing = {"passed": False}
    assert combine_with_existing_delivery_gate(False, passing) is False
    assert combine_with_existing_delivery_gate(True, failing) is False
    assert combine_with_existing_delivery_gate(True, passing) is True
    with pytest.raises(TypeError):
        combine_with_existing_delivery_gate(True, None)


def test_public_report_has_only_scalars_no_biometrics():
    profile = calibrate_ptbr_narration_profile(_owner_rows())
    result = evaluate_ptbr_narration_gate(_candidate(embedding=[0.1, 0.2], transcript="texto privado"), profile)
    report = build_public_gate_report(result, profile)
    blob = json.dumps(report)
    for banned in ("embedding", "texto privado", "transcript", "runtime_path"):
        assert banned not in blob
    assert report["biometric_material_included"] is False
    assert report["human_final_authority"] == "BR_OWNER_V1_LUIZ"
    assert report["owner_rule_id"] == "OWNER_RULE_20261019_PTBR_ULTRA_PROFESSIONAL_NARRATION"


def test_owner_rule_recorded_verbatim_and_hash_bound():
    from pathlib import Path
    from app.services.agents_policy_validation_service import validate_agents_policy
    root = Path(__file__).resolve().parents[1]
    doc = (root / "docs/policy/owner_authorizations.md").read_text(encoding="utf-8")
    assert ('"Se a voz não estiver com qualidade Português BR ultra profissional não será aprovada. '
            'Confere isso com exclusividade e excelência máxima."') in doc
    assert "OWNER_RULE_20261019_PTBR_ULTRA_PROFESSIONAL_NARRATION" in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert validate_agents_policy(root).status == "PASS"
