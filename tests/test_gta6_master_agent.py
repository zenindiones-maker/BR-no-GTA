from __future__ import annotations

from app.services.ai_provider import AIResponse
from app.services.gta6_master_agent import GTA6MasterAgent


class FakeAIProvider:
    def generate(self, prompt: str) -> AIResponse:
        return AIResponse(
            text=(
                '{"action":"RESEARCH",'
                '"reason":"research needed",'
                '"priority":"HIGH",'
                '"confidence":0.9}'
            )
        )


def test_master_agent_runs_brain_then_exactly_one_action():
    calls: list[str] = []

    agent = GTA6MasterAgent(
        ai_provider=FakeAIProvider(),
    )

    agent.dispatcher._actions["RESEARCH"] = (
        "br_research_run",
        lambda: calls.append("research") or {"ok": True},
    )

    result = agent.run_once()

    assert result.decision.action == "RESEARCH"
    assert result.action.action == "RESEARCH"
    assert result.action.tool == "br_research_run"
    assert result.action.success is True
    assert result.action.result == {"ok": True}
    assert calls == ["research"]


def test_master_agent_wait_does_not_execute_action():
    calls: list[str] = []

    class WaitAIProvider:
        def generate(self, prompt: str) -> AIResponse:
            return AIResponse(
                text=(
                    '{"action":"WAIT",'
                    '"reason":"nothing to do",'
                    '"priority":"LOW",'
                    '"confidence":0.99}'
                )
            )

    agent = GTA6MasterAgent(
        ai_provider=WaitAIProvider(),
    )

    agent.dispatcher._actions["RESEARCH"] = (
        "br_research_run",
        lambda: calls.append("research"),
    )

    result = agent.run_once()

    assert result.decision.action == "WAIT"
    assert result.action.action == "WAIT"
    assert result.action.tool is None
    assert result.action.success is True
    assert calls == []


def test_master_agent_result_is_serializable():
    agent = GTA6MasterAgent(
        ai_provider=FakeAIProvider(),
    )

    agent.dispatcher._actions["RESEARCH"] = (
        "br_research_run",
        lambda: {"items": 3},
    )

    result = agent.run_once()
    payload = agent.to_dict(result)

    assert payload["decision"]["action"] == "RESEARCH"
    assert payload["action"]["action"] == "RESEARCH"
    assert payload["action"]["tool"] == "br_research_run"
    assert payload["action"]["result"] == {"items": 3}
