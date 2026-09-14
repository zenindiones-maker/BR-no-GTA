from __future__ import annotations
import json
from app.integrations.deepseek_harness import server
from app.services.gta6_brain import BrainDecision


def test_operational_mcp_tools_are_registered():
    names={tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert names == {"br_observe","br_knowledge_query","br_research_run","br_route","br_editorial_process_next","br_gta6_monitor_run_once","br_master_run_once","br_youtube_pode_postar","br_youtube_publish_next","br_capabilities_discover","br_capability_execute"}


def test_route_tool_returns_metadata_without_authorization():
    payload=json.loads(server.br_route(intent="code review quality",authorized_action="DEVELOPMENT",required_capability_id="addy:code-review-and-quality",domain="development"))
    decision=payload["result"]
    assert decision["selected_capability_id"] == "addy:code-review-and-quality"
    assert decision["selected_provider"] is None
    assert "authorization_id" not in decision


def test_editorial_process_next_routes_provider_under_harness(monkeypatch):
    captured={}
    selected_provider=object()
    def fake_select(*,provider_name=None,authorization,routing_decision=None):
        captured["authorization"]=authorization
        captured["provider_authorization"]=authorization
        captured["routing"]=routing_decision
        assert provider_name is None
        return routing_decision.selected_provider, selected_provider
    def fake_process(*,ai_provider,brain_decision=None,execution_context=None):
        assert ai_provider is selected_provider
        captured["execution_context"]=execution_context
        return {"status":"completed"}
    monkeypatch.setattr(server,"select_harness_ai_provider",fake_select)
    monkeypatch.setattr(server,"process_next_editorial_queue_item",fake_process)
    payload=json.loads(server.br_editorial_process_next())
    result=payload["result"]
    assert captured["routing"].selected_capability_id == "editorial.process"
    assert captured["routing"].selected_provider == "nvidia_nim"
    assert (
        captured["routing"].selected_model
        == "nvidia/nemotron-3-super-120b-a12b"
    )
    assert captured["authorization"].subject == "provider:nvidia_nim"
    assert captured["execution_context"]["authorized_action"] == "EDITORIAL"
    assert captured["execution_context"]["authorization_subject"] == "action:EDITORIAL"
    assert captured["execution_context"]["execution_id"]
    assert captured["execution_context"]["issued_by"] == "deepseek_harness"
    assert result["harness_routing"]["decision"]["routing_id"]
    assert result["harness_routing"]["authorization_id"] == captured["execution_context"]["authorization_id"]
    assert result["harness_routing"]["provider_authorization_id"] == captured["provider_authorization"].authorization_id


def test_master_run_once_harness_issues_authorization(monkeypatch):
    captured={}
    class FakeMasterAgent:
        def __init__(self, ai_provider=None):
            captured["provider"] = ai_provider
        def recommend(self): return BrainDecision(action="RESEARCH",reason="needed",priority="HIGH",confidence=.9)
        def execute_authorized(self, decision, authorization):
            captured["decision"]=decision; captured["authorization"]=authorization
            return {"action":"RESEARCH","success":True}
    monkeypatch.setattr(server,"GTA6MasterAgent",FakeMasterAgent)
    def fake_select(*,provider_name=None,authorization,routing_decision=None):
        captured["provider_authorization"] = authorization
        return routing_decision.selected_provider, object()
    monkeypatch.setattr(server,"select_harness_ai_provider",fake_select)
    payload=json.loads(server.br_master_run_once())
    assert payload["result"]["success"] is True
    assert captured["provider"] is not None
    assert captured["provider_authorization"].authorized_action == "DECISION"
    assert captured["authorization"].issued_by == "deepseek_harness"
    assert captured["authorization"].subject == "action:RESEARCH"


def test_youtube_pode_postar_issues_publication_authorization(monkeypatch):
    captured={}
    def fake(*,publication_id,authorization):
        captured["auth"]=authorization; return {"id":publication_id,"status":"published"}
    monkeypatch.setattr(server,"make_youtube_publication_public_with_google",fake)
    payload=json.loads(server.br_youtube_pode_postar(publication_id=42))
    assert payload["result"]["status"] == "published"
    assert captured["auth"].authorized_action == "PUBLICATION"
    assert captured["auth"].subject == "youtube:publication:42"


def test_capability_execute_generates_ids_inside_harness_boundary(monkeypatch):
    captured={}
    def fake_executor(capability,payload): captured["payload"]=payload; return {"ok":True}
    monkeypatch.setattr(server,"execute_codex_addy_capability",fake_executor)
    payload=json.loads(server.br_capability_execute(capability_id="addy:code-review-and-quality",authorized_action="DEVELOPMENT",payload_json='{"task":"review"}'))
    evidence=payload["result"]
    assert evidence["authority"] == "deepseek_harness"
    assert evidence["harness_decision_id"] and evidence["execution_id"]
    assert captured["payload"] == {"task":"review"}


def test_higgsfield_remains_blocked_under_persisted_harness_authorization():
    payload=json.loads(server.br_capability_execute(capability_id="higgsfield-generate",authorized_action="EXECUTION",payload_json='{"prompt":"x"}'))
    evidence=payload["result"]
    assert evidence["status"] == "BLOCKED" and evidence["authority"] == "deepseek_harness"
