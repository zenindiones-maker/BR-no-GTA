"""Regression boundaries for manual-only learning proof and safe scheduling.

These are static safety contracts; they do not prove a runtime has been promoted.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / ".github/workflows/continuous-intelligence-schedule-proof.yml"
OPERATION = ROOT / ".github/workflows/continuous-intelligence-operation.yml"


def test_learning_proof_requires_explicit_identity_and_is_never_cron_dispatched():
    data = PROOF.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in data
    assert "REQUEST_ID: ${{ inputs.request_id }}" in data
    assert "PROOF_REQUEST_ID_INVALID_OR_MISSING" in data
    assert "-f mode=\"proof\"" in data
    assert "-f trigger_kind=\"workflow_dispatch\"" in data
    assert "on:\n  schedule:" not in data
    assert 'cron: "*/5 * * * *"' not in data
    assert "REAL_SCHEDULE_DISPATCH=PASS" not in data


def test_normal_continuous_scheduler_remains_scheduled():
    data = OPERATION.read_text(encoding="utf-8")
    assert 'cron: "17 */6 * * *"' in data
    assert "continuous-intelligence-executor.yml" in data
    assert 'mode="proof"' not in data


def test_dispatch_reconciliation_failure_never_becomes_zero_runs():
    data = OPERATION.read_text(encoding="utf-8")
    assert "DUPLICATE_RECONCILIATION_UNAVAILABLE_BLOCKED" in data
    assert "DUPLICATE_RECONCILIATION_WINDOW_TRUNCATED_BLOCKED" in data
    assert "jq --arg title" in data
    assert "2>/dev/null || echo 0" not in data
    assert "if: steps.duplicate.outputs.duplicate != 'true'" in data


def test_existing_pinned_target_not_silently_replaced():
    data = OPERATION.read_text(encoding="utf-8")
    assert "DEPLOYMENT_POLICY_BINDING=PASS" in data
    assert "EXPECTED_POLICY_SHA256" in data
    assert "expected_target_sha=" in data
    assert "config/continuous_operation_deployment.json" in data
