"""Ficha de avaliação do Luiz: o ouvido dele é a autoridade final."""
import pytest

from app.services.owner_voice_human_audition_pack_service import (
    OWNER_SCORING_CRITERIA,
    build_owner_scoring_sheet,
    build_owner_scoring_sheet_message,
    evaluate_owner_scoring,
)


def test_sheet_has_the_six_owner_criteria():
    assert [c["id"] for c in OWNER_SCORING_CRITERIA] == [
        "naturalidade", "sotaque_br", "pronuncia_nomes_gta", "ritmo", "emocao", "artefatos",
    ]
    sheet = build_owner_scoring_sheet(pack_id="P1", labels=["A", "B"], gate_reports={"A": {"passed": True}})
    assert sheet["final_authority"] == "BR_OWNER_V1_LUIZ"
    assert sheet["scale"] == {"min": 1, "max": 5}
    assert set(sheet["candidates"]) == {"A", "B"}
    assert sheet["candidates"]["A"]["objective_gate_passed"] is True
    assert sheet["candidates"]["B"]["objective_gate_passed"] is False
    msg = build_owner_scoring_sheet_message(sheet)
    for word in ("Naturalidade", "Sotaque BR", "Pronúncia dos nomes do GTA", "Ritmo", "Emoção", "Artefatos"):
        assert word in msg


def test_only_owner_approval_with_all_scores_high_certifies():
    scores = {c["id"]: 5 for c in OWNER_SCORING_CRITERIA}
    ok = evaluate_owner_scoring(scores, owner_decision="APPROVE", objective_gate_passed=True)
    assert ok["certified"] is True
    low = evaluate_owner_scoring({**scores, "sotaque_br": 3}, owner_decision="APPROVE", objective_gate_passed=True)
    assert low["certified"] is False and "SCORE_BELOW_4:sotaque_br" in low["reasons"]
    rej = evaluate_owner_scoring(scores, owner_decision="REJECT", objective_gate_passed=True)
    assert rej["certified"] is False
    gate = evaluate_owner_scoring(scores, owner_decision="APPROVE", objective_gate_passed=False)
    assert gate["certified"] is False and "OBJECTIVE_PTBR_GATE_NOT_PASSED" in gate["reasons"]
    with pytest.raises(ValueError):
        evaluate_owner_scoring({**scores, "ritmo": 7}, owner_decision="APPROVE", objective_gate_passed=True)
    missing = dict(scores); missing.pop("emocao")
    assert "SCORE_MISSING:emocao" in evaluate_owner_scoring(missing, owner_decision="APPROVE", objective_gate_passed=True)["reasons"]


def test_single_clone_control_message_carries_scoring_sheet():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts/owner_voice_single_clone_delivery.py"
    spec = importlib.util.spec_from_file_location("scoring_delivery_script", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    api = mod.TelegramSingleCloneApi(
        "t", identity_gate="PASS", content_audio_prescreen="PASS", review_token="x" * 16,
        identity_anchor_telegram_input_id=1, pronunciation_reference_telegram_input_ids=[2],
        vice_city_reference_telegram_input_id=None,
    )
    assert "Ficha de avaliação" in api.control_text
    for c in OWNER_SCORING_CRITERIA:
        assert c["label"] in api.control_text
    assert len(api.control_text) < 4096
