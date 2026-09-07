from __future__ import annotations

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
