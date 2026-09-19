from __future__ import annotations

from app.database import harness_learning_repository
from app.services.ai_provider import AIResponse
from app.services import gta6_brain_harness_service as brain_service
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request


class _FakeProvider:
    def generate(self, prompt: str) -> AIResponse:
        assert "GTA6 Brain" in prompt
        return AIResponse(
            text='{"action":"WAIT","reason":"No queued work in canonical state.","priority":"LOW","confidence":0.98}',
            provider="fake",
            model="fake-model",
            finish_reason="stop",
        )


def test_gta6_brain_is_selectable_but_cannot_authorize_execution(monkeypatch):
    capability_id = brain_service.GTA6_BRAIN_CAPABILITY_ID
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="consult GTA6 domain specialist for next operational action",
            authorized_action="DECISION",
            domain="gta6-decision",
            task_class="gta6-domain-decision",
            goal_id="goal-brain-unit",
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"capability:{capability_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": "goal-brain-unit",
        },
    )

    def fake_select(*, routing_decision, authorization):
        assert routing_decision.selected_provider
        return routing_decision.selected_provider, _FakeProvider()

    monkeypatch.setattr(brain_service, "select_harness_ai_provider", fake_select)
    try:
        evidence = brain_service.execute_authorized_gta6_brain_decision(
            authorization=authorization,
            routing_decision=routing,
            payload={
                "mission_id": "mission-brain-unit",
                "task_id": "domain-decision",
                "goal_id": "goal-brain-unit",
                "input_refs": ["state:canonical-db"],
            },
        )
    finally:
        consume_harness_authorization(authorization)

    assert evidence.status == "EXECUTED"
    assert evidence.result["brain_decision"]["action"] == "WAIT"
    assert evidence.result["execution_authorized"] is False
    receipt = evidence.result["receipt"]
    assert receipt["agent_id"] == "gta6-brain"
    assert receipt["proven_live"] is True
    assert receipt["returned_to_harness"] is True

    episodes = harness_learning_repository.list_episodes(
        domain="gta6-decision",
        task_class="gta6-domain-decision",
        limit=20,
    )
    assert len(episodes) == 1
    assert episodes[0]["capability_id"] == capability_id
    assert episodes[0]["actual_outcome"]["observed"] is True
    assert episodes[0]["status"] == "COMPLETED"
