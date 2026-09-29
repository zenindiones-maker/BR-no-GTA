from __future__ import annotations

import json

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from scripts.telegram_conversational_control_canary import (
    _typed_task_result_bindings_are_canonical,
)


def _write_task_result(tmp_path, *, task_id: str, capability_id: str) -> None:
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    assert record is not None
    payload = {
        "schema": "task-result-envelope/v1",
        "mission_id": "telegram-canary-regression",
        "task_id": task_id,
        "capability_id": capability_id,
        "executor_binding": record.executor_binding,
        "status": "COMPLETED",
        "elapsed_ms": 1.0,
    }
    (tmp_path / f"{task_id}-1.json").write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


def test_binding_proof_uses_typed_task_results_not_audit_event_shape(tmp_path):
    # These observability events intentionally have no executor binding.
    # Their presence/order must not influence execution-result validation.
    audit_events = [
        {
            "event": "INPUT_CONTRACT_VALID",
            "task_id": "fact-check",
            "capability_id": "gta6.fact-check",
            "executor_binding": None,
        },
        {
            "event": "TASK_PRECONDITION_PASSED",
            "task_id": "fact-check",
            "capability_id": "gta6.fact-check",
            "executor_binding": None,
        },
        {
            "event": "TASK_COMPLETED_REUSED",
            "task_id": "production-management",
            "capability_id": "youtube.department.production-management",
            "executor_binding": None,
        },
    ]
    assert audit_events

    _write_task_result(
        tmp_path,
        task_id="fact-check",
        capability_id="gta6.fact-check",
    )
    _write_task_result(
        tmp_path,
        task_id="production-management",
        capability_id="youtube.department.production-management",
    )

    proof = _typed_task_result_bindings_are_canonical(tmp_path)
    assert proof["status"] == "PASS"
    assert proof["task_result_count"] == 2
    assert proof["audit_stream_consulted"] is False


def test_binding_proof_fails_closed_on_typed_result_executor_mismatch(tmp_path):
    record = GLOBAL_CAPABILITY_REGISTRY.get("gta6.fact-check")
    assert record is not None
    payload = {
        "schema": "task-result-envelope/v1",
        "mission_id": "telegram-canary-regression",
        "task_id": "fact-check",
        "capability_id": "gta6.fact-check",
        "executor_binding": "evil.direct.executor",
        "status": "COMPLETED",
        "elapsed_ms": 1.0,
    }
    (tmp_path / "fact-check-1.json").write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )

    proof = _typed_task_result_bindings_are_canonical(tmp_path)
    assert proof["status"] == "FAIL"
    assert proof["failure_class"] == "EXECUTOR_BINDING_MISMATCH"
    assert proof["expected_executor_binding"] == record.executor_binding
