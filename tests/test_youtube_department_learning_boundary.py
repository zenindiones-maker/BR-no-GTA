from app.services.harness_ai_provider_service import HarnessAIProviderEvidence
from app.database import harness_learning_repository
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.youtube_department_service import execute_youtube_specialist_via_harness


def test_tubegent_specialist_returns_receipt_and_persists_learning_episode():
    capability_id = "youtube.department.content-strategy"
    task_class = "synergy-content-strategy"
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="derive a grounded YouTube content angle from verified GTA6 evidence",
            authorized_action="EDITORIAL",
            domain="youtube-department",
            task_class=task_class,
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject=f"capability:{capability_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    try:
        canonical = execute_youtube_specialist_via_harness(
            authorization=authorization,
            routing_decision=routing,
            payload={
                "mission_id": "mission-tubegent-observed",
                "task_id": "content-strategy",
                "goal_id": "goal-tubegent-observed",
                "task_class": task_class,
                "objective": "derive a grounded content angle",
                "evidence_refs": ["claim:verified-1", "source:rockstar"],
            },
        )
    finally:
        consume_harness_authorization(authorization)

    assert canonical.success is True
    assert canonical.capability_id == capability_id
    assert canonical.executor == "app.services.youtube_department_service.execute_youtube_specialist_capability"
    assert canonical.result["receipt"]["status"] == "COMPLETED"
    assert canonical.result["receipt"]["returned_to_harness"] is True
    assert canonical.result["receipt"]["agent_id"] == "tubegent-content-strategy"

    episodes = harness_learning_repository.list_episodes(
        domain="youtube-department",
        task_class=task_class,
        limit=20,
    )
    matching = [item for item in episodes if item["capability_id"] == capability_id]
    assert len(matching) == 1
    episode = matching[0]
    assert episode["status"] == "COMPLETED"
    assert episode["actual_outcome"]["observed"] is True
    assert episode["actual_outcome"]["success"] is True
    assert episode["lineage"]["routing_id"] == routing.routing_id
    assert "claim:verified-1" in episode["evidence_refs"]


def test_tubegent_semantic_reasoning_uses_harness_selected_provider(monkeypatch):
    capability_id = "youtube.department.script-review"
    task_class = "synergy-script-review-semantic"
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="review a GTA6 script using verified evidence",
            authorized_action="EDITORIAL",
            domain="youtube-department",
            task_class=task_class,
            goal_id="goal-tubegent-semantic",
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject=f"capability:{capability_id}",
        harness_decision_id="decision-tubegent-semantic",
        execution_id="execution-tubegent-semantic",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )

    def fake_generate(*, prompt, authorization, provider_name=None, routing_decision=None, selector=None):
        assert routing_decision is not None
        assert routing_decision.selected_provider == "opencode"
        assert routing_decision.selected_capability_id == "ai.reasoning.text"
        assert "verified_claim" in prompt
        return HarnessAIProviderEvidence(
            provider="opencode",
            status="EXECUTED",
            active=True,
            authority="deepseek_harness",
            authorized_action="EDITORIAL",
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            authorization_id=authorization.authorization_id,
            result={
                "text": (
                    "Findings: claim is verified by Rockstar evidence. "
                    "Risks: do not overstate inference. Recommendation: retain factual framing. "
                    "Missing evidence: independent corroboration for speculative implications."
                ),
                "model": "oc/big-pickle",
            },
            routing=routing_decision.to_dict(),
            model="oc/big-pickle",
            executor_binding=routing_decision.selected_provider_executor_binding,
            evidence_refs=("provider-routing:semantic-test", "prompt-sha256:test"),
        )

    monkeypatch.setattr(
        "app.services.provider_health_service.semantic_provider_health",
        lambda: {"eligible_zero_cost_provider_ids": ["opencode"]},
    )
    monkeypatch.setattr(
        "app.services.harness_ai_provider_service.execute_harness_ai_generation",
        fake_generate,
    )
    try:
        canonical = execute_youtube_specialist_via_harness(
            authorization=authorization,
            routing_decision=routing,
            payload={
                "mission_id": "mission-tubegent-semantic",
                "task_id": "script-review",
                "goal_id": "goal-tubegent-semantic",
                "task_class": task_class,
                "objective": "review narrative readiness without inventing facts",
                "evidence_refs": ["claim:verified-1", "source:rockstar"],
                "semantic_context": {
                    "verified_claim": "Rockstar source confirms the supplied factual statement",
                    "source_tier": "official",
                },
            },
        )
    finally:
        consume_harness_authorization(authorization)

    assert canonical.success is True
    assert canonical.model == "oc/big-pickle"
    assert canonical.result["semantic_provider"] == "opencode"
    assert canonical.result["semantic_model"] == "oc/big-pickle"
    assert "Findings:" in canonical.result["semantic_analysis"]
    receipt = canonical.result["receipt"]
    assert receipt["external_call_performed"] is True
    assert receipt["provider"] == "opencode"
    assert "provider-routing:semantic-test" in receipt["evidence_refs"]

    episodes = harness_learning_repository.list_episodes(
        domain="youtube-department",
        task_class=task_class,
        limit=20,
    )
    matching = [item for item in episodes if item["capability_id"] == capability_id]
    assert len(matching) == 1
    assert matching[0]["actual_outcome"]["observed"] is True
    assert matching[0]["actual_outcome"]["success"] is True
