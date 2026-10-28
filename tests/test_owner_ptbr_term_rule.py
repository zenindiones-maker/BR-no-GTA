"""Proposed GTA-term coverage rule in the PT-BR pro gate (pending owner confirmation).

2 owner occurrences = covered (existing phoneme bound check); 1 = covered only
with Luiz's ear rating >= 4 on 'pronuncia_nomes_gta'; 0 = uncovered. Until Luiz
confirms the rule, a single occurrence fails closed (no loosening).
"""
from __future__ import annotations

import pytest

from app.services import owner_voice_ptbr_narration_gate_service as S
from app.services.owner_voice_human_audition_pack_service import evaluate_owner_scoring
from tests.test_owner_voice_ptbr_narration_gate import _candidate, _owner_rows


def _eval(terms, monkeypatch=None, confirmed=None):
    if confirmed is not None:
        monkeypatch.setattr(S, "TERM_RULE_OWNER_CONFIRMED", confirmed)
    return S.evaluate_ptbr_narration_gate(_candidate(terms=terms), S.calibrate_ptbr_narration_profile(_owner_rows()))


def _t(term, occ, **kw):
    row = {"term": term, "asr_recognized": True, "phoneme_error_rate": 0.1, "owner_reference_bound": 0.2,
           "owner_occurrences": occ}
    row.update(kw)
    return row


def test_rule_is_recorded_as_proposed_and_pending():
    assert S.TERM_RULE_ID == "PROPOSED_TERM_RULE_20261019_MIN2_OR_1_WITH_OWNER_EAR_GE4"
    assert S.TERM_RULE_OWNER_CONFIRMED is False
    res = _eval([_t("Vice City", 3)])
    assert res["passed"] is True
    assert res["term_rule"] == {"id": S.TERM_RULE_ID, "owner_confirmed": False,
                                "status": "PENDING_OWNER_CONFIRMATION", "min_occurrences": 2,
                                "single_occurrence_requires_owner_ear_score": 4}
    assert res["terms"][0]["coverage"] == "COVERED_MIN2"


def test_two_occurrences_still_need_the_phoneme_bound():
    res = _eval([_t("Jason", 2, phoneme_error_rate=0.5)])
    assert "TERM_PHONEMES_OUTSIDE_OWNER_BOUND:Jason" in res["fail_reasons"]


def test_zero_occurrences_is_uncovered():
    res = _eval([_t("Port Gellhorn", 0, owner_reference_bound=None)])
    assert "OWNER_TERM_UNCOVERED:Port Gellhorn" in res["fail_reasons"]
    assert res["terms"][0]["coverage"] == "UNCOVERED"


def test_single_occurrence_fails_closed_while_rule_unconfirmed():
    res = _eval([_t("Rockstar Games", 1, owner_reference_bound=None)])
    assert res["passed"] is False
    assert "TERM_RULE_SINGLE_OCCURRENCE_PENDING_OWNER_CONFIRMATION:Rockstar Games" in res["fail_reasons"]
    assert res["pending_owner_ear_terms"] == []


def test_single_occurrence_after_confirmation_defers_to_owner_ear(monkeypatch):
    res = _eval([_t("Rockstar Games", 1, owner_reference_bound=None)], monkeypatch, True)
    assert res["passed"] is True
    assert res["pending_owner_ear_terms"] == ["Rockstar Games"]
    assert res["terms"][0]["coverage"] == "COVERED_MIN1_PENDING_OWNER_EAR"
    assert res["terms"][0]["weaker_single_occurrence"] is True
    # Still must be recognized by ASR.
    res2 = _eval([_t("Rockstar Games", 1, owner_reference_bound=None, asr_recognized=False)], monkeypatch, True)
    assert "TERM_NOT_RECOGNIZED:Rockstar Games" in res2["fail_reasons"]


def test_legacy_rows_without_occurrences_keep_old_behavior():
    row = {"term": "Lucia", "asr_recognized": True, "phoneme_error_rate": 0.1, "owner_reference_bound": None}
    res = _eval([row])
    assert "OWNER_TERM_REFERENCE_MISSING:Lucia" in res["fail_reasons"]


def test_owner_scoring_requires_ear_ge4_for_single_occurrence_terms():
    scores = {"naturalidade": 5, "sotaque_br": 5, "pronuncia_nomes_gta": 3, "ritmo": 5, "emocao": 5, "artefatos": 5}
    out = evaluate_owner_scoring(scores, owner_decision="APPROVE", objective_gate_passed=True,
                                 pending_owner_ear_terms=["Rockstar Games"])
    assert "TERM_SINGLE_OCCURRENCE_EAR_BELOW_4:Rockstar Games" in out["reasons"]
    scores["pronuncia_nomes_gta"] = 4
    ok = evaluate_owner_scoring(scores, owner_decision="APPROVE", objective_gate_passed=True,
                                pending_owner_ear_terms=["Rockstar Games"])
    assert not [r for r in ok["reasons"] if r.startswith("TERM_SINGLE")]


def test_public_report_carries_term_rule_and_pending_terms(monkeypatch):
    res = _eval([_t("Rockstar Games", 1, owner_reference_bound=None)], monkeypatch, True)
    rep = S.build_public_gate_report(res, S.calibrate_ptbr_narration_profile(_owner_rows()))
    assert rep["term_rule"]["id"] == S.TERM_RULE_ID
    assert rep["pending_owner_ear_terms"] == ["Rockstar Games"]


def test_runner_passes_owner_occurrences_from_term_index():
    import inspect
    from app.services import owner_voice_ptbr_narration_runner as R
    assert "term_owner_occurrences" in inspect.signature(R.run_ptbr_narration_gate).parameters
    src = inspect.getsource(R.run_ptbr_narration_gate)
    assert '"owner_occurrences"' in src
