from __future__ import annotations

import json

from app.integrations.deepseek_harness import server


def test_operational_mcp_tools_are_registered():
    tools = server.mcp._tool_manager.list_tools()

    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "br_observe",
        "br_knowledge_query",
        "br_research_run",
        "br_editorial_process_next",
        "br_gta6_monitor_run_once",
        "br_master_run_once",
        "br_youtube_pode_postar",
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


def test_knowledge_query_returns_serialized_context(monkeypatch):
    context = object()

    monkeypatch.setattr(
        server,
        "query_gta6_knowledge_context",
        lambda *, query: context,
    )
    monkeypatch.setattr(
        server,
        "knowledge_context_to_dict",
        lambda value: {
            "memory_id": 42,
            "content": "GTA VI terá uma nova informação confirmada.",
            "confidence": 9.0,
            "scope": "gta6",
        },
    )

    payload = json.loads(
        server.br_knowledge_query(
            query="GTA VI",
        )
    )

    assert payload == {
        "operation": "br_knowledge_query",
        "result": {
            "memory_id": 42,
            "content": "GTA VI terá uma nova informação confirmada.",
            "confidence": 9.0,
            "scope": "gta6",
        },
    }


def test_master_run_once_delegates_to_master_agent(monkeypatch):
    class FakeMasterAgent:
        def run_once(self):
            return {
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
                    "result": {"items": 3},
                },
            }

    monkeypatch.setattr(
        server,
        "GTA6MasterAgent",
        FakeMasterAgent,
    )

    payload = json.loads(server.br_master_run_once())

    assert payload == {
        "operation": "br_master_run_once",
        "result": {
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
                "result": {"items": 3},
            },
        },
    }


def test_youtube_pode_postar_uses_existing_publication_authorization(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        server,
        "make_youtube_publication_public_with_google",
        lambda *, publication_id: (
            calls.append(publication_id)
            or {
                "id": publication_id,
                "status": "published",
            }
        ),
    )

    payload = json.loads(
        server.br_youtube_pode_postar(
            publication_id=42,
        )
    )

    assert calls == [42]
    assert payload == {
        "operation": "br_youtube_pode_postar",
        "result": {
            "id": 42,
            "status": "published",
        },
    }
