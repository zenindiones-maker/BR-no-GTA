from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.services.ai_provider_factory import create_ai_provider
from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)
from app.services.gta6_monitor_worker_service import execute_gta6_monitor
from app.services.gta6_master_agent import GTA6MasterAgent
from app.services.google_youtube_publication_service import (
    make_youtube_publication_public_with_google,
)
from app.services.gta6_observation_service import build_gta6_observation
from app.services.gta6_knowledge_query_service import (
    knowledge_context_to_dict,
    query_gta6_knowledge_context,
)
from app.services.gta6_research_pipeline import run_gta6_research
from app.main import initialize_application


mcp = FastMCP(
    "BR-no-GTA",
)


def _json_result(
    *,
    operation: str,
    result: Any,
) -> str:
    """Serialize a BR operation result for MCP."""
    serialized_result = (
        asdict(result)
        if is_dataclass(result)
        else result
    )

    return json.dumps(
        {
            "operation": operation,
            "result": serialized_result,
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
def br_knowledge_query(query: str) -> str:
    """
    Query the GTA6 Knowledge Brain.

    Returns the most relevant persisted knowledge context,
    including confidence and evidence lineage.
    """
    context = query_gta6_knowledge_context(
        query=query,
    )

    if context is None:
        result = {
            "status": "no_knowledge",
            "query": query,
            "reason": "Nenhum conhecimento relevante encontrado no GTA6 Knowledge Brain.",
        }
    else:
        result = knowledge_context_to_dict(context)

    return _json_result(
        operation="br_knowledge_query",
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

    if result is None:
        result = {
            "status": "no_work",
            "executed": False,
            "reason": "Nenhum item queued disponível na fila editorial.",
        }

    return _json_result(
        operation="br_editorial_process_next",
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


@mcp.tool()
def br_master_run_once() -> str:
    """
    Execute one official GTA6 Master Agent control cycle.

    The GTA6 Brain decides the authorized action and the Master Agent
    dispatches only that action through the existing BR services.
    """
    agent = GTA6MasterAgent()
    result = agent.run_once()
    return _json_result(
        operation="br_master_run_once",
        result=result,
    )


@mcp.tool()
def br_youtube_pode_postar(publication_id: int) -> str:
    """
    Explicit authorization gate for public YouTube publication.

    This operation is intentionally separate from the GTA6 Brain YOUTUBE
    action. YOUTUBE may upload pending content, while this operation
    authorizes the existing uploaded -> published transition.
    """
    result = make_youtube_publication_public_with_google(
        publication_id=publication_id,
    )
    return _json_result(
        operation="br_youtube_pode_postar",
        result=result,
    )


def main() -> None:
    """Run the BR MCP server over stdio."""
    initialize_application()
    mcp.run(
        transport="stdio",
    )


if __name__ == "__main__":
    main()
