from __future__ import annotations

from hashlib import sha256
import json

from scripts.continuous_state_checkpoint import (
    validate_attempt_payload,
    validate_checkpoint_manifest,
)


def test_checkpoint_manifest_rejects_stale_or_corrupt_digest():
    payload = b"sqlite-bytes"
    digest = sha256(payload).hexdigest()
    manifest = {
        "schema": "continuous-operation-state/v1",
        "run_id": 123,
        "target_sha": "a" * 40,
        "database_file": "continuous.db",
        "database_sha256": digest,
        "canonical_memory_plane": "BR_SQLITE",
        "transport": "GITHUB_ACTIONS_ARTIFACT_CHECKPOINT",
        "artifact_is_second_memory_plane": False,
        "TERMUX_HEAVY_PROCESSING": "NO",
    }
    assert validate_checkpoint_manifest(manifest, database_sha256=digest) is True
    assert validate_checkpoint_manifest(manifest, database_sha256="b" * 64) is False
    assert validate_checkpoint_manifest({**manifest, "schema": "stale/v0"}, database_sha256=digest) is False


def test_failed_attempt_requires_stable_fingerprint_and_target_identity():
    payload = {
        "schema": "ContinuousOperationAttempt/v1",
        "run_id": "36572055458",
        "target_ref": "work/gate6f-analytics-learning",
        "target_sha": "a" * 40,
        "workflow_revision": "b" * 40,
        "trigger_kind": "schedule",
        "started_at": "2026-09-29T12:00:00+00:00",
        "finished_at": "2026-09-29T12:01:00+00:00",
        "status": "FAIL",
        "failure_class": "CONTRACT_VIOLATION",
        "failure_fingerprint": "c" * 64,
        "retryability": "NOT_RETRYABLE_ON_SAME_EXECUTABLE_SHA",
        "causal_task_id": "research",
        "causal_step": "READ_RESEARCH_COMPLETION_METRICS",
        "exception_type": "KeyError",
        "sanitized_error": "elapsed_seconds",
        "evidence_refs": [],
        "artifact_refs": [],
        "side_effects_started": "UNKNOWN_REQUIRES_RECONCILIATION",
        "side_effects_settled": "NOT_PROVEN",
        "next_allowed_transition": "CODE_FIX_REQUIRED",
        "wake_condition": "TARGET_SHA_CHANGED_OR_EXPLICIT_RETRY_AFTER_FIX",
    }
    assert validate_attempt_payload(payload) is True
    assert validate_attempt_payload({**payload, "failure_fingerprint": ""}) is False
    assert validate_attempt_payload({**payload, "target_sha": "main"}) is False


def test_success_attempt_does_not_require_failure_fingerprint():
    payload = {
        "schema": "ContinuousOperationAttempt/v1",
        "run_id": "1",
        "target_ref": "work/gate6f-analytics-learning",
        "target_sha": "a" * 40,
        "workflow_revision": "b" * 40,
        "trigger_kind": "schedule",
        "started_at": "2026-09-29T12:00:00+00:00",
        "finished_at": "2026-09-29T12:01:00+00:00",
        "status": "PASS",
        "failure_class": None,
        "failure_fingerprint": None,
        "retryability": "NOT_APPLICABLE",
        "causal_task_id": None,
        "causal_step": "CONTINUOUS_CYCLE_SETTLED",
        "exception_type": None,
        "sanitized_error": None,
        "evidence_refs": [],
        "artifact_refs": [],
        "side_effects_started": "BOUNDED_BY_POLICY",
        "side_effects_settled": "PASS",
        "next_allowed_transition": "SCHEDULE_NEXT_DUE",
        "wake_condition": None,
    }
    assert validate_attempt_payload(json.loads(json.dumps(payload))) is True
