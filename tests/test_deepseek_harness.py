from __future__ import annotations

import json

from app.integrations.deepseek_harness import server


def test_master_agent_mcp_tool_is_registered():
    tools = server.mcp._tool_manager.list_tools()

    tool_names = {tool.name for tool in tools}

    assert "br_gta6_master_agent_run_once" in tool_names


def test_master_agent_mcp_tool_is_official_master_agent_entrypoint(
    monkeypatch,
):
    calls: list[str] = []

    class FakeMasterAgent:
        def __init__(self, *, ai_provider):
            self.ai_provider = ai_provider

        def run_once(self):
            calls.append("run_once")
            return {"fake": "cycle"}

        @staticmethod
        def to_dict(result):
            return result

    monkeypatch.setattr(
        server,
        "GTA6MasterAgent",
        FakeMasterAgent,
    )

    monkeypatch.setattr(
        server,
        "create_ai_provider",
        lambda: object(),
    )

    payload = json.loads(
        server.br_gta6_master_agent_run_once()
    )

    assert calls == ["run_once"]

    assert payload == {
        "operation": "br_gta6_master_agent_run_once",
        "result": {
            "fake": "cycle",
        },
    }
