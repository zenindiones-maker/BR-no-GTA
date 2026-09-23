import json

from app.database import harness_learning_repository as learning_repository
from app.database.schema import initialize_schema
from app.services.nvidia_model_learning_service import (
    record_nvidia_semantic_model_observation,
)
from app.services.provider_health_service import model_health


def test_timeout_observation_enters_existing_learning_and_health_plane(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "learning.db"))
    initialize_schema()
    model_id = "z-ai/glm-5.3"
    result = record_nvidia_semantic_model_observation(
        model_id=model_id,
        goal_id="goal-timeout",
        routing_id="route-timeout",
        success=False,
        latency_ms=54000.0,
        failure_class="timeout",
        retry_count=0,
        run_id="35806537500",
    )
    assert result["memory_id"]
    health = model_health("nvidia_nim", model_id)
    assert health.availability == "DEGRADED"
    assert health.failure_class == "timeout"
    assert health.source == "LEARNING_PLANE_LIVE_EVIDENCE"
    memories = learning_repository.list_memories(
        memory_type="FAILURE",
        domain="ai",
        task_class="semantic-mission-planning",
    )
    assert any(
        (item.get("metadata") or {}).get("model_id") == model_id
        for item in memories
    )
