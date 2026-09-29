from __future__ import annotations

import json

from app.services.continuous_operation_attempt_service import (
    ATTEMPT_SCHEMA,
    build_failure_attempt,
    failure_fingerprint,
    persist_attempt,
    same_sha_known_defect_hold,
)


def test_keyerror_is_nonretryable_contract_violation_on_same_sha(tmp_path):
    attempt = build_failure_attempt(
        exc=KeyError("elapsed_seconds"),
        run_id="36572055458",
        target_ref="work/gate6f-analytics-learning",
        target_sha="a" * 40,
        workflow_revision="b" * 40,
        trigger_kind="schedule",
        started_at="2026-09-29T12:00:00+00:00",
        causal_task_id="research",
        causal_step="READ_RESEARCH_COMPLETION_METRICS",
    )
    assert attempt.schema == ATTEMPT_SCHEMA
    assert attempt.failure_class == "CONTRACT_VIOLATION"
    assert attempt.retryability == "NOT_RETRYABLE_ON_SAME_EXECUTABLE_SHA"
    assert attempt.next_allowed_transition == "CODE_FIX_REQUIRED"
    assert attempt.wake_condition == "TARGET_SHA_CHANGED_OR_EXPLICIT_RETRY_AFTER_FIX"
    assert same_sha_known_defect_hold(attempt, target_sha="a" * 40) is True
    assert same_sha_known_defect_hold(attempt, target_sha="c" * 40) is False

    path = persist_attempt(attempt, artifact_dir=tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["failure_fingerprint"] == attempt.failure_fingerprint
    assert saved["side_effects_settled"] == "NOT_PROVEN"


def test_failure_fingerprint_is_stable_for_same_cause_and_revision():
    kwargs = dict(
        target_sha="a" * 40,
        workflow_revision="b" * 40,
        failure_class="CONTRACT_VIOLATION",
        exception_type="KeyError",
        causal_step="READ_RESEARCH_COMPLETION_METRICS",
        sanitized_error="'elapsed_seconds'",
    )
    first = failure_fingerprint(**kwargs)
    second = failure_fingerprint(**kwargs)
    assert first == second
    assert failure_fingerprint(**{**kwargs, "target_sha": "c" * 40}) != first


def test_attempt_sanitizes_secret_shaped_failure_text():
    attempt = build_failure_attempt(
        exc=RuntimeError("token=super-secret-value ghp_abcdefghijklmnop"),
        run_id="1",
        target_ref="work/gate6f-analytics-learning",
        target_sha="a" * 40,
        workflow_revision="b" * 40,
        trigger_kind="schedule",
        started_at="2026-09-29T12:00:00+00:00",
    )
    assert "super-secret-value" not in attempt.sanitized_error
    assert "ghp_abcdefghijklmnop" not in attempt.sanitized_error
