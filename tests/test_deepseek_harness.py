from __future__ import annotations
import json

import pytest

from app.services.harness_capability_service import CapabilityEvidence
from app.services import harness_mcp_capability_execution
from app.services.harness_authorization_service import (
    authorization_to_context,
    validate_harness_authorization,
)
from app.integrations.deepseek_harness import server
from app.services.gta6_brain import BrainDecision
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    RoutingPolicyError,
    route_harness_request,
)


def _assert_zero_cost_nvidia_primary(routing):
    assert routing.selected_provider == "nvidia_nim"
    assert routing.selected_model
    assert routing.fallback_allowed is False
    assert routing.fallback_occurred is False
    assert routing.policy_metadata["zero_cost_operation"] is True


def test_operational_mcp_tools_are_registered():
    names={tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert names == {"br_observe","br_knowledge_query","br_research_run","br_route","br_editorial_process_next","br_execution_process_next","br_gta6_monitor_run_once","br_master_run_once","br_youtube_publication_preview","br_youtube_publication_reconcile","br_youtube_pode_postar","br_youtube_publish","br_youtube_publish_reconcile","br_youtube_publish_next","br_capabilities_discover","br_capability_execute"}


def test_route_tool_returns_metadata_without_authorization():
    payload=json.loads(server.br_route(intent="code review quality",authorized_action="DEVELOPMENT",required_capability_id="addy:code-review-and-quality",domain="development"))
    decision=payload["result"]
    assert decision["selected_capability_id"] == "addy:code-review-and-quality"
    assert decision["selected_provider"] is None
    assert decision["policy_metadata"]["zero_cost_operation"] is True
    assert "authorization_id" not in decision


def test_zero_cost_routing_fails_closed_when_nvidia_auth_is_not_materialized(
    monkeypatch,
):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(RoutingPolicyError) as exc_info:
        route_harness_request(
            HarnessRoutingRequest(
                intent="process next GTA6 editorial queue item with AI reasoning",
                authorized_action="EDITORIAL",
                domain="editorial",
                required_capability_id="editorial.process",
                provider_required=True,
                provider_domain="ai",
                preferred_providers=("nvidia_nim",),
                fallback_allowed=False,
            )
        )

    assert exc_info.value.evidence["zero_cost_operation"] is True
    assert exc_info.value.evidence["fallback_allowed"] is False
    rejected = exc_info.value.evidence["rejected_candidates"]
    assert any(
        item["candidate_id"].startswith("ai.provider.nvidia-nim.")
        and "provider_health=AUTH_REQUIRED" in item["reasons"]
        for item in rejected
    )


def test_editorial_provider_boundary_selects_primary_zero_cost_provider(
    monkeypatch,
):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-only-nvidia-key")
    routing, provider_authorization, ai_provider = server._route_editorial_provider()

    _assert_zero_cost_nvidia_primary(routing)
    assert routing.authorized_action == "EDITORIAL"
    assert provider_authorization.issued_by == "deepseek_harness"
    assert provider_authorization.authorized_action == "EDITORIAL"
    assert provider_authorization.subject == "provider:nvidia_nim"
    assert provider_authorization.status == "active"
    assert provider_authorization.lineage["routing_id"] == routing.routing_id
    assert (
        provider_authorization.lineage["selected_capability_id"]
        == routing.selected_capability_id
    )
    assert provider_authorization.lineage["selected_provider"] == "nvidia_nim"
    assert provider_authorization.lineage["selected_model"] == routing.selected_model
    assert ai_provider.__class__.__name__ == "NvidiaNimProviderAdapter"
    assert ai_provider.model == routing.selected_model


def test_master_run_once_selects_primary_zero_cost_provider(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-only-nvidia-key")
    captured = {}

    def select(*, routing_decision, authorization, **kwargs):
        captured["routing"] = routing_decision
        captured["provider_authorization"] = authorization
        captured["provider"] = object()
        return "opencode", captured["provider"]

    class FakeMasterAgent:
        def __init__(self, *, ai_provider):
            assert ai_provider is captured["provider"]

        def recommend(self):
            return BrainDecision(
                action="WAIT",
                reason="zero-cost routing regression proof",
                priority="LOW",
                confidence=1.0,
            )

        def execute_authorized(self, decision, authorization):
            captured["decision"] = decision
            captured["action_authorization"] = authorization
            return {"status": "completed"}

    monkeypatch.setattr(server, "select_harness_ai_provider", select)
    monkeypatch.setattr(server, "GTA6MasterAgent", FakeMasterAgent)

    payload = json.loads(server.br_master_run_once())
    routing = captured["routing"]
    _assert_zero_cost_nvidia_primary(routing)
    assert routing.authorized_action == "DECISION"
    assert captured["provider_authorization"].issued_by == "deepseek_harness"
    assert captured["provider_authorization"].authorized_action == "DECISION"
    assert captured["provider_authorization"].subject == "provider:nvidia_nim"
    assert captured["decision"].action == "WAIT"
    assert captured["action_authorization"].issued_by == "deepseek_harness"
    assert captured["action_authorization"].authorized_action == "WAIT"
    assert captured["action_authorization"].subject == "action:WAIT"
    assert payload["result"] == {"status": "completed"}


def test_youtube_publication_preview_is_read_only(monkeypatch):
    captured = {}

    def fake(publication_id):
        captured["publication_id"] = publication_id
        return {
            "publication_id": publication_id,
            "PUBLICATION_READY": True,
            "approval_granted": False,
            "boundary": "READ_ONLY_NO_PUBLICATION_AUTHORITY",
        }

    monkeypatch.setattr(server, "build_youtube_publication_preview", fake)
    payload = json.loads(server.br_youtube_publication_preview(publication_id=42))
    assert captured["publication_id"] == 42
    assert payload["result"]["PUBLICATION_READY"] is True
    assert payload["result"]["approval_granted"] is False


def test_youtube_publication_reconcile_targets_exact_publication(monkeypatch):
    captured = {}

    def fake(*, publication_id):
        captured["publication_id"] = publication_id
        return {"id": publication_id, "status": "published"}

    monkeypatch.setattr(server, "reconcile_youtube_publication_visibility_with_google", fake)
    payload = json.loads(server.br_youtube_publication_reconcile(publication_id=42))
    assert captured["publication_id"] == 42
    assert payload["result"]["status"] == "published"


def test_youtube_pode_postar_uses_targeted_harness_publication_boundary(monkeypatch):
    captured = {}

    def fake(publication_id, **kwargs):
        captured["publication_id"] = publication_id
        captured.update(kwargs)
        return {
            "publication": {"id": publication_id, "status": "published"},
            "routing": {"selected_capability_id": "youtube.publish-public"},
            "authorization_id": "auth-publication-42",
            "canonical_execution_result": {"success": True},
        }

    monkeypatch.setattr(server, "publish_targeted_publication", fake)
    payload = json.loads(server.br_youtube_pode_postar(publication_id=42))
    assert captured["publication_id"] == 42
    assert captured["approval_source"] == "user"
    assert captured["approval_operation"] == "br_youtube_pode_postar"
    assert payload["result"]["publication"]["status"] == "published"
    assert payload["result"]["routing"]["selected_capability_id"] == "youtube.publish-public"
    assert payload["result"]["canonical_execution_result"]["success"] is True


def test_youtube_publish_dispatches_exact_cloud_target(monkeypatch):
    captured = {}

    def fake(publication_id):
        captured["publication_id"] = publication_id
        return {
            "status": "IN_PROGRESS",
            "publication_id": publication_id,
            "upload_run_id": 35050000001,
            "canonical_execution_result": {"success": True},
        }

    monkeypatch.setattr(server, "dispatch_targeted_private_upload", fake)
    payload = json.loads(server.br_youtube_publish(publication_id=43))
    assert captured["publication_id"] == 43
    assert payload["result"]["status"] == "IN_PROGRESS"
    assert payload["result"]["upload_run_id"] == 35050000001
    assert payload["result"]["canonical_execution_result"]["success"] is True


def test_youtube_publish_reconcile_targets_exact_publication(monkeypatch):
    captured = {}

    def fake(publication_id):
        captured["publication_id"] = publication_id
        return {
            "status": "UPLOADED",
            "publication": {"id": publication_id, "status": "uploaded"},
            "upload_run_id": 35050000001,
        }

    monkeypatch.setattr(server, "reconcile_targeted_private_upload", fake)
    payload = json.loads(server.br_youtube_publish_reconcile(publication_id=43))
    assert captured["publication_id"] == 43
    assert payload["result"]["status"] == "UPLOADED"
    assert payload["result"]["publication"]["id"] == 43


def test_capability_execute_generates_ids_inside_harness_boundary():
    payload=json.loads(server.br_capability_execute(
        capability_id="media.discovery",
        authorized_action="EXECUTION",
        payload_json=json.dumps({
            "topic": "Vice City",
            "results": [{
                "title": "Grand Theft Auto VI Trailer 2",
                "url": "https://www.youtube.com/watch?v=example",
                "source": "youtube",
                "description": "GTA VI Vice City Lucia Jason",
                "source_authority": "official",
            }],
        }),
    ))
    evidence=payload["result"]
    canonical=payload["evidence"]
    assert evidence["authority"] == "deepseek_harness"
    assert evidence["harness_decision_id"] and evidence["execution_id"]
    assert canonical["authority"] == "deepseek_harness"
    assert canonical["execution_id"] == evidence["execution_id"]
    assert canonical["authorization_id"] == evidence["authorization_id"]
    assert canonical["routing_id"] == evidence["harness_routing"]["routing_id"]
    assert canonical["capability_id"] == "media.discovery"
    assert canonical["result"]["status"] == "EXECUTED"
    assert canonical["result"]["candidate_count"] == 1


def test_capability_execute_uses_canonical_addy_boundary_not_generic_executor(monkeypatch):
    calls = {"legacy": 0, "canonical": 0}

    def substituted_legacy_executor(capability, payload):
        calls["legacy"] += 1
        raise AssertionError("generic Addy executor must never receive canonical Addy execution")

    def canonical_addy_executor(*, authorization, routing_decision, payload):
        calls["canonical"] += 1
        return CapabilityEvidence(
            capability_id=routing_decision.selected_capability_id,
            provider="opencode",
            status="EXECUTED",
            active=True,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={"boundary_test": "canonical_addy"},
            boundary="test canonical Addy boundary",
        )

    monkeypatch.setattr(server, "execute_codex_addy_capability", substituted_legacy_executor)
    monkeypatch.setattr(
        harness_mcp_capability_execution,
        "execute_authorized_addy_skill",
        canonical_addy_executor,
    )
    payload=json.loads(server.br_capability_execute(
        capability_id="addy:code-review-and-quality",
        authorized_action="DEVELOPMENT",
        payload_json='{"task":"review"}',
    ))
    assert calls == {"legacy": 0, "canonical": 1}
    assert payload["result"]["status"] == "EXECUTED"
    assert payload["result"]["result"]["boundary_test"] == "canonical_addy"
    assert payload["evidence"]["success"] is True


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


def test_targeted_execution_preserves_explicit_media_knowledge_in_harness_lineage(monkeypatch):
    captured = {}

    def execute(execution_context, *, goal_id, knowledge_id):
        authorization = validate_harness_authorization(
            execution_context,
            expected_action="EXECUTION",
            expected_subject="action:EXECUTION",
            expected_execution_id=execution_context["execution_id"],
        )
        captured["lineage"] = authorization.lineage
        captured["args"] = (goal_id, knowledge_id)
        return {"status": "selected"}

    monkeypatch.setattr(server, "process_next_production_execution", execute)
    payload = json.loads(server.br_execution_process_next(goal_id="goal-a", knowledge_id=7))

    assert payload["result"] == {"status": "selected"}
    assert captured["args"] == ("goal-a", 7)
    assert captured["lineage"]["goal_id"] == "goal-a"
    assert captured["lineage"]["knowledge_id"] == 7


@pytest.mark.parametrize("knowledge_id", [0, -1, True, "7"])
def test_execution_rejects_invalid_media_knowledge_identity(knowledge_id):
    with pytest.raises(ValueError, match="positive integer"):
        server.br_execution_process_next(goal_id="goal-a", knowledge_id=knowledge_id)


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
