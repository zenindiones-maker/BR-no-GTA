"""Lint determinístico antes de editorial_ok (Luiz, 18/10/2026 23:22).

Rejeita comparação com outros jogos fora da evidência, especulação (talvez,
provavelmente...), dia da semana errado e número/data sem fonte, e aponta as
linhas culpadas.
"""
from __future__ import annotations

import json

import pytest

from app.services import editorial_script_lint as lint
from scripts import script_first_gate as g

EVIDENCE = [
    "Grand Theft Auto VI será lançado para PlayStation 5 e PS5 Pro em 19 de novembro de 2026.",
    "Standard Edition: Grand Theft Auto VI · Pacote Vintage Vice City · Um mês de GTA+ · Pré-carregamento 7 dias antes — R$449,90",
    "Ultimate Edition — R$549,90",
]


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setenv("BR_EDITORIAL_TODAY", "2026-10-18")
    monkeypatch.delenv("BR_EDITORIAL_VERIFIED_SOURCES", raising=False)


def _codes(text: str) -> set[str]:
    return {f["code"] for f in lint.lint_script(text, evidence=EVIDENCE)}


def test_clean_script_passes():
    text = (
        "Hoje, 18 de outubro de 2026, faltam 32 dias para o GTA VI.\n\n"
        "O jogo chega em 19 de novembro de 2026, uma quinta-feira, no PS5 e PS5 Pro.\n\n"
        "A Standard Edition custa R$449,90 e a Ultimate Edition sai por R$549,90, "
        "com pré-carregamento 7 dias antes."
    )
    assert lint.lint_script(text, evidence=EVIDENCE) == []


def test_hedges_rejected():
    assert "SPECULATIVE_HEDGE" in _codes("Talvez o jogo tenha modo online no dia 19 de novembro de 2026.")
    assert "SPECULATIVE_HEDGE" in _codes("Provavelmente a Rockstar mostra mais.")
    assert "SPECULATIVE_HEDGE" in _codes("Pode ser que venha uma edição física.")
    assert "SPECULATIVE_HEDGE" in _codes("Os rumores falam de PC.")


def test_other_game_comparison_rejected_unless_in_evidence():
    assert "OTHER_GAME_NOT_IN_EVIDENCE" in _codes("Igual ao Red Dead Redemption 2, o GTA VI atrasou.")
    assert "OTHER_GAME_NOT_IN_EVIDENCE" in _codes("O GTA V vendeu muito.")
    assert "OTHER_GAME_NOT_IN_EVIDENCE" in _codes("Lembra de Bonnie e Clyde?")
    assert "OTHER_GAME_NOT_IN_EVIDENCE" not in _codes("O GTA VI chega ao PS5.")
    assert lint.lint_script("O GTA V vendeu muito.", evidence=["O GTA V vendeu muito."]) == []


def test_weekday_must_match_calendar():
    assert "WEEKDAY_MISMATCH" in _codes("O lançamento é numa sexta-feira, 19 de novembro de 2026.")
    assert "WEEKDAY_MISMATCH" in _codes("Hoje é segunda-feira.")
    assert "WEEKDAY_UNANCHORED" in _codes("Na terça-feira sai mais coisa.")
    assert "WEEKDAY_MISMATCH" not in _codes("Hoje, domingo, 18 de outubro de 2026.")


def test_unsourced_numbers_and_dates_rejected():
    assert "UNSOURCED_NUMBER" in _codes("O mapa tem 400 quilômetros.")
    assert "UNSOURCED_NUMBER" in _codes("A edição custa R$399,90.")
    assert "UNSOURCED_DATE" in _codes("O trailer 3 sai em 5 de dezembro.")
    assert "UNSOURCED_NUMBER" in _codes("Serão cento e cinquenta missões.")


def test_findings_report_offending_line():
    findings = lint.lint_script("Linha boa no PS5.\n\nTalvez saia no PC.", evidence=EVIDENCE)
    assert findings and findings[0]["line"] == 2
    assert "Talvez saia no PC." in findings[0]["text"]


def test_write_editorial_script_blocks_before_editorial_ok(tmp_path, monkeypatch):
    report = tmp_path / "lint.json"
    monkeypatch.setenv("BR_SCRIPT_LINT_REPORT", str(report))
    result = {"production_plan": {"scenes": [
        {"narration": "O GTA VI chega em 19 de novembro de 2026.", "duration_seconds": 6},
        {"narration": "Provavelmente igual ao GTA V.", "duration_seconds": 6}]},
        "script": {"id": 9, "title": "Guia"},
        "sources": [{"url": "https://www.rockstargames.com/VI"}]}
    with pytest.raises(g.ScriptGateError) as err:
        g.write_editorial_script(result, root=tmp_path, evidence=EVIDENCE)
    assert "SCRIPT_LINT_FAILED" in str(err.value)
    assert "Provavelmente igual ao GTA V." in str(err.value)
    assert not (tmp_path / "ep-0009").exists()
    payload = json.loads(report.read_text())
    assert payload["status"] == "FAIL" and payload["findings"]


def test_server_passes_verified_claims_as_lint_evidence():
    from pathlib import Path
    body = Path("app/integrations/deepseek_harness/server.py").read_text(encoding="utf-8")
    assert "write_editorial_script(result, goal_id=goal_id, evidence=" in body
