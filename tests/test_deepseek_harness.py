from __future__ import annotations

import json

from app.integrations.deepseek_harness import server


def test_operational_mcp_tools_are_registered():
    tools = server.mcp._tool_manager.list_tools()

    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "br_observe",
        "br_research_run",
        "br_editorial_process_next",
        "br_execution_run_once",
        "br_gta6_monitor_run_once",
    }

def test_editorial_process_next_reports_no_work(monkeypatch):
    monkeypatch.setattr(server, "create_ai_provider", lambda: object())
    monkeypatch.setattr(
        server,
        "process_next_editorial_queue_item",
        lambda *, ai_provider: None,
    )

    payload = json.loads(server.br_editorial_process_next())

    assert payload == {
        "operation": "br_editorial_process_next",
        "result": {
            "status": "no_work",
            "executed": False,
            "reason": "Nenhum item queued disponível na fila editorial.",
        },
    }
