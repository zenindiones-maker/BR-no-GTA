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
