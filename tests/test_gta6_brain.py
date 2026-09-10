from __future__ import annotations

import json

import pytest

from app.services.ai_provider import AIResponse
from app.services.gta6_brain import BrainContext, GTA6Brain


class FakeAIProvider:
    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> AIResponse:
        self.prompts.append(prompt)
        return AIResponse(text=self.response)


def test_brain_parses_valid_decision(monkeypatch):
    provider = FakeAIProvider(
        json.dumps(
            {
                "action": "RESEARCH",
                "reason": "Não há evidência de novidade no monitor.",
                "priority": "HIGH",
                "confidence": 0.91,
            }
        )
    )

    context = BrainContext(
        research_count=2,
        ideas_count=2,
        ideas_by_status={"approved": 2},
        editorial_count=2,
        editorial_by_decision={"review": 2},
        queue_count=24,
        queue_by_status={"completed": 24},
        active_queue_count=0,
        active_queue_by_status={},
        scripts_count=2,
        scripts_by_status={"draft": 2},
        videos_count=0,
        videos_by_status={},
        youtube_count=0,
        youtube_by_status={},
        monitor_state={
            "url": "https://www.rockstargames.com/newswire",
            "content_hash": "abc",
        },
    )

    brain = GTA6Brain(provider)
    monkeypatch.setattr(brain, "build_context", lambda: context)

    decision = brain.decide()

    assert decision.action == "RESEARCH"
    assert decision.reason == "Não há evidência de novidade no monitor."
    assert decision.priority == "HIGH"
    assert decision.confidence == 0.91
    assert len(provider.prompts) == 1


def test_brain_parses_markdown_json_block():
    provider = FakeAIProvider(
        """```json
{
  "action": "MONITOR",
  "reason": "Verificar as fontes monitoradas.",
  "priority": "MEDIUM",
  "confidence": 0.95
}
```"""
    )

    brain = GTA6Brain(provider)

    decision = brain._parse_decision(provider.response)

    assert decision.action == "MONITOR"
    assert decision.reason == "Verificar as fontes monitoradas."
    assert decision.priority == "MEDIUM"
    assert decision.confidence == 0.95


def test_brain_rejects_invalid_action():
    provider = FakeAIProvider(
        json.dumps(
            {
                "action": "MAKE_SOMETHING_UP",
                "reason": "invalid",
                "priority": "HIGH",
                "confidence": 0.9,
            }
        )
    )

    brain = GTA6Brain(provider)

    with pytest.raises(ValueError, match="Invalid GTA6 Brain action"):
        brain._parse_decision(provider.response)


def test_brain_rejects_invalid_priority():
    provider = FakeAIProvider(
        json.dumps(
            {
                "action": "RESEARCH",
                "reason": "valid reason",
                "priority": "SUPER_HIGH",
                "confidence": 0.9,
            }
        )
    )

    brain = GTA6Brain(provider)

    with pytest.raises(ValueError, match="Invalid GTA6 Brain priority"):
        brain._parse_decision(provider.response)


def test_brain_rejects_invalid_confidence():
    provider = FakeAIProvider(
        json.dumps(
            {
                "action": "RESEARCH",
                "reason": "valid reason",
                "priority": "HIGH",
                "confidence": 1.5,
            }
        )
    )

    brain = GTA6Brain(provider)

    with pytest.raises(
        ValueError,
        match="confidence must be between 0 and 1",
    ):
        brain._parse_decision(provider.response)


def test_brain_rejects_non_json():
    provider = FakeAIProvider("não sou JSON")

    brain = GTA6Brain(provider)

    with pytest.raises(
        ValueError,
        match="returned invalid JSON",
    ):
        brain._parse_decision(provider.response)
