"""Run 39187065060 (18/10/2026): sem data de hoje no prompt, o modelo escreveu
que 19/11/2026 é "uma terça-feira do ano que vem" (é quinta, daqui a um mês) e
puxou histórico de outros jogos da memória. O canal é só conteúdo oficial."""
from app.services import script_generator_service as s


def _prompt(monkeypatch, today="2026-10-18"):
    monkeypatch.setenv("BR_EDITORIAL_TODAY", today)
    return s._build_ai_prompt(title="Guia oficial de lançamento", description="d",
                              research_context=None, editorial_context=None,
                              target_duration_seconds=420.0)


def test_prompt_carries_today_and_days_to_launch(monkeypatch):
    p = _prompt(monkeypatch)
    assert "Data de hoje: 18/10/2026 (domingo)" in p
    assert "America/Sao_Paulo" in p


def test_prompt_forbids_unanchored_temporal_and_memory_claims(monkeypatch):
    p = _prompt(monkeypatch)
    assert "dia da semana" in p
    assert "memória do modelo" in p
    assert "histórico de outros jogos" in p


def test_today_defaults_to_sao_paulo_clock(monkeypatch):
    monkeypatch.delenv("BR_EDITORIAL_TODAY", raising=False)
    d = s._editorial_today()
    assert d.year >= 2026
