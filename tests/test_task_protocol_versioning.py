import pytest

from app.services.harness_collaboration_service import (
    TASK_PROTOCOL_V1,
    TASK_PROTOCOL_VNEXT,
    TaskEnvelope,
)


def _base():
    return {
        "task_id": "task-a",
        "capability_id": "repository.read-scoped",
        "action": "RESEARCH",
        "objective": "inspect one bounded repository scope",
        "expected_output": "Evidence",
    }


def test_legacy_task_defaults_to_v1():
    task = TaskEnvelope.from_mapping(_base())
    assert task.task_protocol_version == TASK_PROTOCOL_V1


def test_vnext_task_version_roundtrips():
    task = TaskEnvelope.from_mapping({
        **_base(),
        "task_protocol_version": TASK_PROTOCOL_VNEXT,
    })
    assert task.to_dict()["task_protocol_version"] == (
        TASK_PROTOCOL_VNEXT
    )


def test_unknown_task_protocol_version_fails_closed():
    with pytest.raises(ValueError, match="task_protocol_version"):
        TaskEnvelope.from_mapping({
            **_base(),
            "task_protocol_version": "TaskProtocol/latest",
        })
