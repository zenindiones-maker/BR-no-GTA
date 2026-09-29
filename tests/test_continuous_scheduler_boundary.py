from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.continuous_operation_deployment_service import (
    DEPLOYMENT_SCHEMA,
    build_logical_cycle_id,
    load_continuous_operation_deployment,
    validate_continuous_operation_deployment,
)


def _deployment(**overrides):
    payload = {
        "schema": DEPLOYMENT_SCHEMA,
        "execution_ref": "work/gate6f-analytics-learning",
        "expected_sha": "a" * 40,
        "workflow_contract_version": "continuous-executor/v2",
        "policy_sha256": "b" * 64,
        "enabled": True,
        "promoted_at": "2026-09-29T14:00:00+00:00",
        "promotion_evidence_refs": [
            "github-actions:36577417064:continuous-focused",
            "github-actions:36577801020:ci",
        ],
        "cadence_seconds": 21600,
        "cycle_kind": "CONTINUOUS_INTELLIGENCE",
    }
    payload.update(overrides)
    return payload


def test_deployment_descriptor_is_typed_and_exact_sha_bound(tmp_path):
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(_deployment()), encoding="utf-8")

    loaded = load_continuous_operation_deployment(path)
    assert loaded["schema"] == DEPLOYMENT_SCHEMA
    assert loaded["expected_sha"] == "a" * 40
    assert loaded["execution_ref"] == "work/gate6f-analytics-learning"
    assert loaded["enabled"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_sha", "main"),
        ("policy_sha256", "abc"),
        ("execution_ref", "../unsafe"),
        ("workflow_contract_version", ""),
        ("enabled", False),
        ("promotion_evidence_refs", []),
    ],
)
def test_deployment_descriptor_fails_closed_on_unpromoted_or_unsafe_state(field, value):
    payload = _deployment(**{field: value})
    with pytest.raises((ValueError, PermissionError)):
        validate_continuous_operation_deployment(payload)


def test_scheduled_cycle_identity_is_deterministic_inside_same_due_window():
    deployment = _deployment()
    first = build_logical_cycle_id(
        deployment,
        trigger_kind="schedule",
        now="2026-09-29T14:17:01+00:00",
    )
    second = build_logical_cycle_id(
        deployment,
        trigger_kind="schedule",
        now="2026-09-29T17:59:59+00:00",
    )
    next_window = build_logical_cycle_id(
        deployment,
        trigger_kind="schedule",
        now="2026-09-29T18:17:01+00:00",
    )
    assert first == second
    assert first != next_window


def test_manual_proof_identity_requires_explicit_request_id():
    deployment = _deployment()
    with pytest.raises(ValueError, match="request_id"):
        build_logical_cycle_id(
            deployment,
            trigger_kind="workflow_dispatch",
            mode="proof",
            now="2026-09-29T14:17:01+00:00",
        )
    one = build_logical_cycle_id(
        deployment,
        trigger_kind="workflow_dispatch",
        mode="proof",
        request_id="focused-proof-1",
        now="2026-09-29T14:17:01+00:00",
    )
    two = build_logical_cycle_id(
        deployment,
        trigger_kind="workflow_dispatch",
        mode="proof",
        request_id="focused-proof-1",
        now="2026-09-29T14:18:01+00:00",
    )
    assert one == two


def test_scheduler_workflow_contains_no_business_runtime():
    text = Path(".github/workflows/continuous-intelligence-operation.yml").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "continuous_intelligence_cycle.py",
        "bootstrap_hermes_agent.py",
        "pip install -r requirements.txt",
        "continuous_state_checkpoint.py restore",
        "continuous_due_gate.py",
        "TELEGRAM_BOT_TOKEN",
    )
    for marker in forbidden:
        assert marker not in text
    assert "continuous-intelligence-executor.yml" in text
    assert "actions: write" in text
    assert "SCHEDULER_BUSINESS_LOGIC=0" in text


def test_executor_requires_exact_promoted_sha_before_runtime():
    text = Path(".github/workflows/continuous-intelligence-executor.yml").read_text(
        encoding="utf-8"
    )
    assert "expected_target_sha" in text
    assert "TARGET_SHA_DRIFT_BLOCKED" in text
    assert 'ref: ${{ inputs.expected_target_sha }}' in text
    assert "continuous_intelligence_cycle.py" in text
    assert "CONTINUOUS_EXECUTOR_TARGET_SHA_EXACT_MATCH=PASS" in text
    assert "actions/checkout@" in text
    assert "@v4" not in text
    assert "actions/setup-python@" in text
    assert "@v5" not in text


def test_policy_sha_is_content_addressed():
    payload = b'{"schema":"continuous-operation-policy/v1"}\n'
    assert hashlib.sha256(payload).hexdigest() != "0" * 64


def test_scheduler_separates_non_coalescible_proof_concurrency():
    text = Path(".github/workflows/continuous-intelligence-operation.yml").read_text(
        encoding="utf-8"
    )
    assert "br-continuous-intelligence-scheduler-" in text
    assert "inputs.request_id" in text
    assert "coalescible" in text


def test_executor_workflow_fallback_attempt_preserves_original_trigger_kind():
    text = Path(".github/workflows/continuous-intelligence-executor.yml").read_text(
        encoding="utf-8"
    )
    assert "ORIGINAL_TRIGGER_KIND: ${{ inputs.trigger_kind }}" in text
    assert '"trigger_kind":os.environ.get("ORIGINAL_TRIGGER_KIND")' in text


def test_executor_persists_incident_dedup_before_attempt_artifact_upload():
    workflow = Path(".github/workflows/continuous-intelligence-executor.yml").read_text(
        encoding="utf-8"
    )
    settlement = workflow.index(
        "Settle workflow-level failure if cycle could not write an attempt"
    )
    incident = workflow.index("Settle actionable incident dedup state")
    upload = workflow.index("Upload durable attempt settlement")

    assert settlement < incident < upload
    assert "scripts/continuous_incident_settlement.py" in workflow
    assert "--prior-attempt artifacts/continuous-operation/prior-attempt.json" in workflow
    assert "--current-attempt artifacts/continuous-operation/continuous-operation-attempt.json" in workflow
    assert "ACTIONABLE_ALERT_REQUIRED" in workflow
