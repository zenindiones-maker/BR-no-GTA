from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.services.ai_provider_factory import create_ai_provider
from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)
from app.services.execution_cycle_service import run_execution_cycle
from app.services.gta6_monitor_worker_service import execute_gta6_monitor
from app.services.gta6_observation_service import build_gta6_observation
from app.services.gta6_research_pipeline import run_gta6_research


mcp = FastMCP(
    "BR-no-GTA",
)


def _json_result(
    *,
    operation: str,
    result: Any,
) -> str:
    """Serialize a BR operation result for MCP."""
    return json.dumps(
        {
            "operation": operation,
            "result": result,
        },
        ensure_ascii=False,
        default=str,
    )



@mcp.tool()
def br_observe() -> str:
    """
    Observe the current GTA6 operational state.

    This is a read-only observation tool for the DeepSeek Harness.
    It does not execute pipelines, call AI, or modify persistence.
    """
    result = build_gta6_observation()
    return _json_result(
        operation="br_observe",
        result=result,
    )


@mcp.tool()
def br_research_run() -> str:
    """
    Execute the official GTA6 research pipeline.

    This delegates entirely to the existing BR research service.
    The MCP layer does not access SQLite directly.
    """
    result = run_gta6_research()

    return _json_result(
        operation="br_research_run",
        result=result,
    )


@mcp.tool()
def br_editorial_process_next() -> str:
    """
    Process the next editorial queue item using the official BR AI provider.

    AI credentials and provider routing remain inside the BR provider layer.
    """
    ai_provider = create_ai_provider()

    result = process_next_editorial_queue_item(
        ai_provider=ai_provider,
    )

    return _json_result(
        operation="br_editorial_process_next",
        result=result,
    )


@mcp.tool()
def br_execution_run_once() -> str:
    """
    Execute one official BR editorial/execution cycle.

    Existing BR services remain responsible for business rules,
    persistence, and execution.
    """
    ai_provider = create_ai_provider()

    result = run_execution_cycle(
        ai_provider=ai_provider,
    )

    return _json_result(
        operation="br_execution_run_once",
        result=result,
    )


@mcp.tool()
def br_gta6_monitor_run_once() -> str:
    """
    Execute one GTA6 monitor cycle.
    """
    result = execute_gta6_monitor()

    return _json_result(
        operation="br_gta6_monitor_run_once",
        result=result,
    )


def main() -> None:
    """Run the BR MCP server over stdio."""
    mcp.run(
        transport="stdio",
    )


if __name__ == "__main__":
    main()
