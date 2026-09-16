from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.global_capability_registry import (
    AVAILABLE,
    FUNCTIONAL,
    GLOBAL_CAPABILITY_REGISTRY,
)
from app.services.telegram_fresh_research_service import (
    FRESH_RESEARCH_CAPABILITY_ID,
    FRESH_RESEARCH_EXECUTOR_BINDING,
    FreshResearchError,
    requires_fresh_research,
    research_fresh_gta6_under_harness,
)
from app.services.telegram_harness_service import chat_under_harness


class FakeFreshTransport:
    def execute(self, *, query: str, execution_id: str):
        assert query
        return (
            {
                "status": "PASS",
                "execution_id": execution_id,
                "query": query,
                "checked_at": "2026-09-16T04:00:00+00:00",
                "official_source_count": 2,
                "secondary_source_count": 1,
                "official_sources": [
                    {
                        "source_name": "Rockstar GTA VI",
                        "url": "https://www.rockstargames.com/VI",
                        "authority": "official",
                        "checked_at": "2026-09-16T04:00:00+00:00",
                        "content_excerpt": "Coming November 19, 2026. Jason and Lucia. Vice City, Leonida.",
                    },
                    {
                        "source_name": "Rockstar Store GTA VI",
                        "url": "https://store.rockstargames.com/game/buy-gta-vi",
                        "authority": "official",
                        "checked_at": "2026-09-16T04:00:00+00:00",
                        "content_excerpt": "Release Date November 19, 2026. Developer Rockstar Games.",
                    },
                ],
                "secondary_sources": [
                    {
                        "source_name": "IGN GTA 6",
                        "title": "Current GTA VI coverage",
                        "summary": "Secondary reporting.",
                        "url": "https://www.ign.com/",
                        "published_at": "2026-09-15",
                        "authority": "secondary",
                    }
                ],
                "source_errors": [],
                "policy": {
                    "official_sources_are_authoritative": True,
                    "secondary_sources_require_corroboration": True,
                    "community_sources_are_signals_only": True,
                    "model_prior_is_not_evidence": True,
                },
            },
            "github-actions:999",
        )


def test_registry_contains_exact_fresh_cloud_research_capability():
    record = GLOBAL_CAPABILITY_REGISTRY.get(FRESH_RESEARCH_CAPABILITY_ID)
    assert record is not None
    assert record.availability == AVAILABLE
    assert record.maturity == FUNCTIONAL
    assert record.domain == "research"
    assert record.allowed_actions == ("RESEARCH",)
    assert record.executor_binding == FRESH_RESEARCH_EXECUTOR_BINDING
    assert record.cost_class == "FREE_NO_BILLING"
    assert record.fallback_eligibility is False
    assert "official Rockstar" in record.security_boundary


@pytest.mark.parametrize(
    "message",
    [
        "Qual é a data oficial atual de GTA VI?",
        "O que a Rockstar confirmou hoje sobre GTA 6?",
        "Quais são as últimas notícias e rumores de GTA 6?",
        "O que você sabe hoje sobre GTA 6?",
    ],
)
def test_current_gta6_questions_require_fresh_research(message):
    assert requires_fresh_research(message) is True


def test_pure_system_question_does_not_force_web_refresh():
    assert requires_fresh_research("Como funciona o sistema BR no GTA?") is False


def test_fresh_research_routes_exact_capability_and_preserves_lineage():
    evidence = research_fresh_gta6_under_harness(
        "Qual é a data oficial atual de GTA VI?",
        transport=FakeFreshTransport(),
    )
    assert evidence.status == "PASS"
    assert evidence.authority == "deepseek_harness"
    assert evidence.official_source_count == 2
    assert evidence.execution_ref == "github-actions:999"
    assert evidence.routing_id
    assert evidence.authorization_id
    assert evidence.execution_id
    assert evidence.packet["official_sources"][0]["authority"] == "official"


def test_current_chat_injects_fresh_official_evidence_before_ai(monkeypatch):
    fresh = research_fresh_gta6_under_harness(
        "Qual é a data oficial atual de GTA VI?",
        transport=FakeFreshTransport(),
    )
    monkeypatch.setattr(
        "app.services.telegram_harness_service.research_fresh_gta6_under_harness",
        lambda message: fresh,
    )

    def fake_ai(*, prompt, authorization, routing_decision):
        assert "November 19, 2026" in prompt
        assert "https://www.rockstargames.com/VI" in prompt
        assert "EVIDENCIA_FRESCA oficial da Rockstar prevalece" in prompt
        assert "model_prior_is_not_evidence" in prompt
        return SimpleNamespace(
            provider="opencode",
            status="EXECUTED",
            active=True,
            authority="deepseek_harness",
            authorized_action="DECISION",
            execution_id=authorization.execution_id,
            result={
                "text": "A data oficial atual é 19 de novembro de 2026, conforme a Rockstar.",
                "model": "oc/big-pickle",
            },
        )

    monkeypatch.setattr(
        "app.services.telegram_harness_service.execute_harness_ai_generation",
        fake_ai,
    )
    progress: list[tuple[str, str]] = []
    result = chat_under_harness(
        "Qual é a data oficial atual de GTA VI?",
        progress_callback=lambda stage, message: progress.append((stage, message)),
    )

    assert "19 de novembro de 2026" in result["answer"]
    assert result["fresh_research_required"] is True
    assert result["fresh_research_status"] == "PASS"
    assert result["fresh_research_checked_at"] == "2026-09-16T04:00:00+00:00"
    assert result["official_source_count"] == 2
    assert result["fresh_research_execution_ref"] == "github-actions:999"
    assert [stage for stage, _ in progress] == ["RESEARCH", "VALIDATION", "REASONING"]


def test_current_chat_fails_closed_when_fresh_official_research_fails(monkeypatch):
    def fail_research(message):
        raise FreshResearchError("source unavailable")

    def must_not_call_ai(**kwargs):
        raise AssertionError("AI model prior must not be used after fresh research failure")

    monkeypatch.setattr(
        "app.services.telegram_harness_service.research_fresh_gta6_under_harness",
        fail_research,
    )
    monkeypatch.setattr(
        "app.services.telegram_harness_service.execute_harness_ai_generation",
        must_not_call_ai,
    )

    result = chat_under_harness("O que a Rockstar confirmou hoje sobre GTA 6?")

    assert result["fresh_research_required"] is True
    assert result["fresh_research_status"] == "FAIL_CLOSED"
    assert "não vou completar" in result["answer"].casefold()
    assert result["provider"] is None
    assert result["fallback_occurred"] is False
