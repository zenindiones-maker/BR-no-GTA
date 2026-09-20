from app.services.opencode_executor_profile_service import OPENCODE_EXECUTOR_SKILL_ID
from app.services.opencode_semantic_incident_service import (
    CONFIRMED_ARTIFACT_ID,
    CONFIRMED_FAILURE_PATTERN,
    CONFIRMED_RUN_ID,
    CONFIRMED_TASK_CLASS,
    reconcile_confirmed_opencode_semantic_tool_failure,
)


def test_confirmed_semantic_tool_incident_is_persisted_idempotently():
    first = reconcile_confirmed_opencode_semantic_tool_failure(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
    )
    second = reconcile_confirmed_opencode_semantic_tool_failure(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
    )

    assert first["failure_pattern"] == CONFIRMED_FAILURE_PATTERN
    assert first["task_class"] == CONFIRMED_TASK_CLASS == "telegram.reasoning"
    assert first["provider"] == "opencode"
    assert first["model"] == "oc/big-pickle"
    assert first["profile_version"] == "v2"

    episode = first["episode"]
    assert episode["status"] == "FAILED"
    assert episode["actual_outcome"]["tool_call_count"] == 6
    assert episode["actual_outcome"]["semantic_agent"] == "build"
    assert episode["actual_outcome"]["provider_exit_code"] == 0
    assert episode["run_ref"] == f"github:run:{CONFIRMED_RUN_ID}"
    assert f"github:artifact:{CONFIRMED_ARTIFACT_ID}" in episode["artifact_refs"]

    memory = first["failure_memory"]
    assert memory["failure_pattern"] == CONFIRMED_FAILURE_PATTERN
    assert memory["task_class"] == "telegram.reasoning"
    assert memory["skill_version"] == "v2"
    assert memory["metadata"]["run_id"] == CONFIRMED_RUN_ID
    assert memory["metadata"]["artifact_id"] == CONFIRMED_ARTIFACT_ID
    assert memory["metadata"]["tool_call_count"] == 6
    assert memory["support_count"] == 1

    assert second["episode"]["episode_id"] == episode["episode_id"]
    assert second["failure_memory"]["memory_id"] == memory["memory_id"]
    assert second["failure_memory"]["support_count"] == 1
