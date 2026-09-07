from __future__ import annotations

from app.database.gta6_master_agent_repository import (
    list_gta6_master_agent_runs,
)
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


def test_master_agent_run_once_persists_decision_and_action():
    agent = GTA6MasterAgent(
        ai_provider=FakeAIProvider(),
    )

    agent.dispatcher._actions["RESEARCH"] = (
        "br_research_run",
        lambda: {"items": 3},
    )

    result = agent.run_once()

    runs = list_gta6_master_agent_runs()

    persisted = [
        run
        for run in runs
        if run["action"] == result.decision.action
        and run["reason"] == result.decision.reason
        and run["result"] == result.action.result
    ]

    assert persisted

    run = persisted[-1]

    assert run["execution_id"]
    assert run["cycle_number"] == 1
    assert run["status"] == "COMPLETED"
    assert run["action"] == "RESEARCH"
    assert run["reason"] == "research needed"
    assert run["priority"] == "HIGH"
    assert run["confidence"] == 0.9
    assert run["tool"] == "br_research_run"
    assert run["success"] is True
    assert run["result"] == {"items": 3}
    assert run["error_type"] is None
    assert run["error"] is None
    assert run["started_at"]
    assert run["completed_at"]


def test_master_agent_wait_is_persisted_without_action_tool():
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

    result = agent.run_once()

    runs = list_gta6_master_agent_runs()

    persisted = [
        run
        for run in runs
        if run["action"] == "WAIT"
        and run["reason"] == "nothing to do"
    ]

    assert persisted

    run = persisted[-1]

    assert result.decision.action == "WAIT"
    assert result.action.tool is None
    assert result.action.success is True

    assert run["status"] == "COMPLETED"
    assert run["tool"] is None
    assert run["success"] is True
    assert run["result"] is None


def test_master_agent_persistence_does_not_change_returned_result():
    agent = GTA6MasterAgent(
        ai_provider=FakeAIProvider(),
    )

    agent.dispatcher._actions["RESEARCH"] = (
        "br_research_run",
        lambda: {"items": 7},
    )

    result = agent.run_once()
    payload = agent.to_dict(result)

    assert payload == {
        "decision": {
            "action": "RESEARCH",
            "reason": "research needed",
            "priority": "HIGH",
            "confidence": 0.9,
        },
        "action": {
            "action": "RESEARCH",
            "tool": "br_research_run",
            "success": True,
            "result": {"items": 7},
        },
    }
