from __future__ import annotations
import json

import pytest

from app.services.harness_authorization_service import (
    authorization_to_context,
    validate_harness_authorization,
)
from app.integrations.deepseek_harness import server
from app.services.gta6_brain import BrainDecision
from app.services.harness_routing_policy_service import RoutingPolicyError


def test_operational_mcp_tools_are_registered():
    names={tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert names == {"br_observe","br_knowledge_query","br_research_run","br_route","br_editorial_process_next","br_execution_process_next","br_gta6_monitor_run_once","br_master_run_once","br_youtube_pode_postar","br_youtube_publish_next","br_capabilities_discover","br_capability_execute"}


def test_route_tool_returns_metadata_without_authorization():
    payload=json.loads(server.br_route(intent="code review quality",authorized_action="DEVELOPMENT",required_capability_id="addy:code-review-and-quality",domain="development"))
    decision=payload["result"]
    assert decision["selected_capability_id"] == "addy:code-review-and-quality"
    assert decision["selected_provider"] is None
    assert decision["policy_metadata"]["zero_cost_operation"] is True
    assert "authorization_id" not in decision


def test_editorial_process_next_fails_closed_when_provider_cost_is_unknown(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Unknown-cost provider must not be selected or executed")

    monkeypatch.setattr(server, "select_harness_ai_provider", unexpected)
    monkeypatch.setattr(server, "process_next_editorial_queue_item", unexpected)

    with pytest.raises(RoutingPolicyError) as exc_info:
        server.br_editorial_process_next()

    assert exc_info.value.evidence["zero_cost_operation"] is True
    rejected = exc_info.value.evidence["rejected_candidates"]
    assert any(
        item["candidate_id"] == "ai.provider.nvidia-nim"
        and "UNKNOWN_COST_PROVIDER_FORBIDDEN" in item["reasons"]
        for item in rejected
    )


def test_master_run_once_fails_closed_when_decision_provider_cost_is_unknown(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("MasterAgent/provider construction must not run after cost rejection")

    monkeypatch.setattr(server, "GTA6MasterAgent", unexpected)
    monkeypatch.setattr(server, "select_harness_ai_provider", unexpected)

    with pytest.raises(RoutingPolicyError) as exc_info:
        server.br_master_run_once()

    assert exc_info.value.evidence["zero_cost_operation"] is True
    rejected = exc_info.value.evidence["rejected_candidates"]
    assert any(
        item["candidate_id"] == "ai.provider.nvidia-nim"
        and "UNKNOWN_COST_PROVIDER_FORBIDDEN" in item["reasons"]
        for item in rejected
    )


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
    canonical=payload["evidence"]
    assert evidence["authority"] == "deepseek_harness"
    assert evidence["harness_decision_id"] and evidence["execution_id"]
    assert canonical["authority"] == "deepseek_harness"
    assert canonical["execution_id"] == evidence["execution_id"]
    assert canonical["authorization_id"] == evidence["authorization_id"]
    assert canonical["routing_id"] == evidence["harness_routing"]["routing_id"]
    assert canonical["capability_id"] == "addy:code-review-and-quality"
    assert canonical["result"] == {"ok": True}
    assert captured["payload"] == {"task":"review"}


def test_higgsfield_remains_blocked_under_persisted_harness_authorization():
    payload=json.loads(server.br_capability_execute(capability_id="higgsfield-generate",authorized_action="EXECUTION",payload_json='{"prompt":"x"}'))
    evidence=payload["result"]
    canonical=payload["evidence"]
    assert evidence["status"] == "BLOCKED" and evidence["authority"] == "deepseek_harness"
    assert canonical["success"] is False
    assert canonical["status"] == "BLOCKED"
    assert canonical["authority"] == "deepseek_harness"


@pytest.mark.parametrize("operation_result", [{"status": "completed"}, None])
def test_execution_process_next_persists_routed_authorization_before_executor(
    monkeypatch, operation_result,
):
    captured = {}
    real_route = server.route_harness_request

    def route(request):
        assert request.authorized_action == "EXECUTION"
        assert request.fallback_allowed is False
        captured["routing"] = real_route(request)
        return captured["routing"]

    def execute(execution_context):
        authorization = validate_harness_authorization(
            execution_context,
            expected_action="EXECUTION",
            expected_subject="action:EXECUTION",
            expected_execution_id=execution_context["execution_id"],
        )
        assert execution_context == authorization_to_context(authorization)
        assert authorization.issued_by == "deepseek_harness"
        assert authorization.harness_decision_id
        assert execution_context["brain_decision_id"] == authorization.harness_decision_id
        routing = captured["routing"]
        assert authorization.lineage == {
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        }
        captured["authorization"] = authorization
        captured["executed"] = True
        return operation_result

    monkeypatch.setattr(server, "route_harness_request", route)
    monkeypatch.setattr(server, "process_next_production_execution", execute)

    payload = json.loads(server.br_execution_process_next())
    assert payload["operation"] == "br_execution_process_next"
    assert payload["result"] == operation_result
    evidence = payload["evidence"]
    authorization = captured["authorization"]
    routing = captured["routing"]
    assert evidence["authority"] == "deepseek_harness"
    assert evidence["authorized_action"] == "EXECUTION"
    assert evidence["execution_id"] == authorization.execution_id
    assert evidence["routing_id"] == routing.routing_id
    assert evidence["authorization_id"] == authorization.authorization_id
    assert evidence["harness_decision_id"] == authorization.harness_decision_id
    assert evidence["capability_id"] == routing.selected_capability_id
    assert evidence["result"] == operation_result
    assert evidence["success"] is True
    assert captured["executed"] is True


@pytest.mark.parametrize("failed_boundary", ["routing", "authorization"])
def test_execution_process_next_fails_closed_before_production(monkeypatch, failed_boundary):
    def blocked(*args, **kwargs):
        raise PermissionError("Harness boundary rejected")

    def unexpected(*args, **kwargs):
        pytest.fail("Production must not run after Harness rejection")

    monkeypatch.setattr(server, "process_next_production_execution", unexpected)
    if failed_boundary == "routing":
        monkeypatch.setattr(server, "route_harness_request", blocked)
        monkeypatch.setattr(server, "issue_harness_authorization", unexpected)
    else:
        monkeypatch.setattr(server, "issue_harness_authorization", blocked)

    with pytest.raises(PermissionError, match="Harness boundary rejected"):
        server.br_execution_process_next()
