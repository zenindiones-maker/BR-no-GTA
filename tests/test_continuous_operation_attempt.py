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


def _incident_attempt(
    *,
    status: str,
    fingerprint: str | None,
    target_sha: str = "a" * 40,
    started_at: str = "2026-09-29T12:00:00+00:00",
    finished_at: str = "2026-09-29T12:00:01+00:00",
    incident_state=None,
):
    payload = {
        "schema": ATTEMPT_SCHEMA,
        "run_id": "1",
        "target_ref": "work/gate6f-analytics-learning",
        "target_sha": target_sha,
        "workflow_revision": "b" * 40,
        "trigger_kind": "schedule",
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "failure_class": "CONTRACT_VIOLATION" if status != "PASS" else None,
        "failure_fingerprint": fingerprint,
        "retryability": (
            "NOT_RETRYABLE_ON_SAME_EXECUTABLE_SHA"
            if status != "PASS"
            else "NOT_APPLICABLE"
        ),
        "causal_task_id": "research" if status != "PASS" else None,
        "causal_step": (
            "PRECHECK_KNOWN_DEFECT_GATE"
            if status == "HELD_KNOWN_DEFECT"
            else "READ_RESEARCH_COMPLETION_METRICS"
        ),
        "exception_type": "KeyError" if status != "PASS" else None,
        "sanitized_error": "'elapsed_seconds'" if status != "PASS" else None,
        "evidence_refs": [],
        "artifact_refs": [],
        "side_effects_started": "NO" if status == "HELD_KNOWN_DEFECT" else "UNKNOWN_REQUIRES_RECONCILIATION",
        "side_effects_settled": "PASS" if status == "HELD_KNOWN_DEFECT" else "NOT_PROVEN",
        "next_allowed_transition": "CODE_FIX_REQUIRED" if status != "PASS" else "SCHEDULE_NEXT_DUE",
        "wake_condition": (
            "TARGET_SHA_CHANGED_OR_EXPLICIT_RETRY_AFTER_FIX"
            if status != "PASS"
            else None
        ),
    }
    if incident_state is not None:
        payload["incident_state"] = incident_state
    return payload


def test_incident_aggregate_opens_once_for_new_failure_fingerprint():
    from scripts.continuous_incident_settlement import settle_incident

    current = _incident_attempt(status="FAIL", fingerprint="f" * 64)
    incident = settle_incident(current_attempt=current, prior_attempt=None)

    assert incident["schema"] == "ContinuousOperationIncident/v1"
    assert incident["incident_fingerprint"] == "f" * 64
    assert incident["first_seen_at"] == current["started_at"]
    assert incident["last_seen_at"] == current["finished_at"]
    assert incident["occurrence_count"] == 1
    assert incident["current_status"] == "OPEN"
    assert incident["target_sha"] == "a" * 40
    assert incident["wake_condition"] == "TARGET_SHA_CHANGED_OR_EXPLICIT_RETRY_AFTER_FIX"
    assert incident["alert_required"] is True
    assert incident["alert_reason"] == "NEW_ACTIONABLE_INCIDENT"


def test_incident_aggregate_suppresses_same_sha_repeat_without_hiding_blocker():
    from scripts.continuous_incident_settlement import settle_incident

    first_attempt = _incident_attempt(status="FAIL", fingerprint="f" * 64)
    first_incident = settle_incident(
        current_attempt=first_attempt,
        prior_attempt=None,
    )
    prior = _incident_attempt(
        status="FAIL",
        fingerprint="f" * 64,
        incident_state=first_incident,
    )
    current = _incident_attempt(
        status="HELD_KNOWN_DEFECT",
        fingerprint="f" * 64,
        started_at="2026-09-29T18:00:00+00:00",
        finished_at="2026-09-29T18:00:01+00:00",
    )

    incident = settle_incident(current_attempt=current, prior_attempt=prior)

    assert incident["first_seen_at"] == first_incident["first_seen_at"]
    assert incident["last_seen_at"] == current["finished_at"]
    assert incident["occurrence_count"] == 2
    assert incident["current_status"] == "HELD_KNOWN_DEFECT"
    assert incident["alert_required"] is False
    assert incident["alert_reason"] == "DUPLICATE_SAME_FINGERPRINT_SUPPRESSED"
    assert incident["wake_condition"] == "TARGET_SHA_CHANGED_OR_EXPLICIT_RETRY_AFTER_FIX"


def test_incident_aggregate_realerts_when_target_sha_or_fingerprint_changes():
    from scripts.continuous_incident_settlement import settle_incident

    prior_incident = settle_incident(
        current_attempt=_incident_attempt(status="FAIL", fingerprint="f" * 64),
        prior_attempt=None,
    )
    prior = _incident_attempt(
        status="HELD_KNOWN_DEFECT",
        fingerprint="f" * 64,
        incident_state=prior_incident,
    )
    current = _incident_attempt(
        status="FAIL",
        fingerprint="e" * 64,
        target_sha="c" * 40,
        started_at="2026-09-29T19:00:00+00:00",
        finished_at="2026-09-29T19:00:01+00:00",
    )

    incident = settle_incident(current_attempt=current, prior_attempt=prior)

    assert incident["incident_fingerprint"] == "e" * 64
    assert incident["target_sha"] == "c" * 40
    assert incident["occurrence_count"] == 1
    assert incident["alert_required"] is True
    assert incident["alert_reason"] == "NEW_ACTIONABLE_INCIDENT"
