from __future__ import annotations

import json

from app.database import harness_learning_repository
from app.services.ai_provider import AIResponse
from app.services import gta6_brain_harness_service as brain_service
from app.services.gta6_domain_projection_service import (
    build_gta6_domain_projection,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


class _SequenceProvider:
    def __init__(self):
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> AIResponse:
        self.prompts.append(prompt)
        return AIResponse(
            text=json.dumps({
                "action": "WAIT",
                "reason": "Use bounded canonical state.",
                "priority": "LOW",
                "confidence": 0.9,
            }),
            provider="fake",
            model="fake",
            finish_reason="stop",
        )


def _capability_route(goal_id: str):
    capability_id = brain_service.GTA6_BRAIN_CAPABILITY_ID
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="consult GTA6 domain specialist",
            authorized_action="DECISION",
            domain="gta6-decision",
            task_class="gta6-domain-decision",
            goal_id=goal_id,
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    auth = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"capability:{capability_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": capability_id,
            "selected_executor_binding": (
                routing.selected_executor_binding
            ),
            "goal_id": goal_id,
        },
    )
    return routing, auth


def test_two_cycle_feedback_loop_reenters_next_projection(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-only-nvidia-key")
    provider = _SequenceProvider()
    monkeypatch.setattr(
        brain_service,
        "select_harness_ai_provider",
        lambda *, routing_decision, authorization: (
            routing_decision.selected_provider,
            provider,
        ),
    )

    routing1, auth1 = _capability_route("goal-cycle")
    try:
        first = brain_service.execute_authorized_gta6_brain_decision(
            authorization=auth1,
            routing_decision=routing1,
            payload={
                "mission_id": "mission-cycle",
                "task_id": "task-cycle",
                "goal_id": "goal-cycle",
            },
        )
    finally:
        consume_harness_authorization(auth1)

    episodes = harness_learning_repository.list_episodes(
        domain="gta6-decision",
        task_class="gta6-domain-decision",
        capability_id="gta6.brain.decide",
        limit=10,
    )
    assert len(episodes) == 1
    episode_id = episodes[0]["episode_id"]

    harness_learning_repository.insert_memory({
        "memory_id": "memory-domain-failure",
        "memory_type": "FAILURE",
        "claim": "Prior GTA6 domain decision missed a quality gate.",
        "domain": "gta6-decision",
        "task_class": "gta6-domain-decision",
        "failure_pattern": "DOMAIN_QUALITY_GATE",
        "source_episode_ids": [episode_id],
        "evidence_refs": [f"episode:{episode_id}"],
        "agent_id": "gta6-brain",
        "capability_id": "gta6.brain.decide",
        "skill_id": None,
        "skill_version": None,
        "source_versions": {},
        "metadata": {},
        "support_count": 1,
        "contradiction_count": 0,
        "confidence": 0.9,
        "status": "ACTIVE",
        "fingerprint": "feedback-loop-memory",
        "created_at": "2026-09-27T12:00:00+00:00",
        "last_verified_at": "2026-09-27T12:00:00+00:00",
    })
    harness_learning_repository.insert_human_correction({
        "correction_id": "correction-domain-1",
        "goal_id": "goal-cycle",
        "task_id": "task-cycle",
        "context": "GTA6 Brain decision",
        "undesired_behavior": "repeat old topic",
        "desired_behavior": "prioritize new supported GTA6 evidence",
        "affected_agent": "gta6-brain",
        "affected_capability": "gta6.brain.decide",
        "affected_skill": None,
        "evidence_refs": [f"episode:{episode_id}"],
        "metadata": {},
        "scope": "LOCAL",
        "status": "CANDIDATE",
        "created_at": "2026-09-27T12:01:00+00:00",
    })

    projection = build_gta6_domain_projection(
        mission_id="mission-cycle",
        task_id="task-cycle",
        goal_id="goal-cycle",
    )
    feedback = projection["decision_feedback"]
    assert (
        feedback["recent_brain_decisions"][0]["episode_ref"]
        == f"episode:{episode_id}"
    )
    assert feedback["recent_brain_decisions"][0]["action"] == "WAIT"
    assert (
        feedback["relevant_failure_memories"][0]["memory_ref"]
        == "memory:memory-domain-failure"
    )
    assert (
        feedback["relevant_human_corrections"][0]["correction_ref"]
        == "human-correction:correction-domain-1"
    )

    routing2, auth2 = _capability_route("goal-cycle")
    try:
        second = brain_service.execute_authorized_gta6_brain_decision(
            authorization=auth2,
            routing_decision=routing2,
            payload={
                "mission_id": "mission-cycle",
                "task_id": "task-cycle",
                "goal_id": "goal-cycle",
            },
        )
    finally:
        consume_harness_authorization(auth2)

    assert first.status == "EXECUTED"
    assert second.status == "EXECUTED"
    assert len(provider.prompts) == 2
    assert episode_id in provider.prompts[1]
    assert "memory-domain-failure" in provider.prompts[1]
    assert "correction-domain-1" in provider.prompts[1]
    assert provider.prompts[0] != provider.prompts[1]
