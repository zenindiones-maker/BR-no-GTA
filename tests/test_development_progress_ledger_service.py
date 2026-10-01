from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from app.services.development_progress_ledger_service import (
    DevelopmentProgressLedger,
    ledger_digest,
    validate_ledger,
)
from app.services.development_continuity_policy_service import (
    DevelopmentContinuityPolicy,
    classify_path,
    validate_recovery_ref,
)


def test_policy_constants_and_recovery_ref_boundary():
    p = DevelopmentContinuityPolicy()
    assert p.required is True
    assert p.rpo_target_seconds == 300
    assert p.rpo_hard_max_seconds == 600
    assert p.resume_rto_target_seconds == 600
    assert p.remote_read_after_write_required is True
    assert p.recovery_ref_fast_forward_only is True
    assert p.force_push_recovery is False
    assert p.side_effect_replay_from_dev_checkpoint is False
    assert validate_recovery_ref("recovery/dev/wave-b-integrity-001") == "recovery/dev/wave-b-integrity-001"
    with pytest.raises(ValueError):
        validate_recovery_ref("work/gate6f-analytics-learning")


def test_path_classification_is_fail_closed():
    assert classify_path("app/services/x.py") == "RECOVERABLE_SOURCE"
    assert classify_path("tests/test_x.py") == "RECOVERABLE_SOURCE"
    assert classify_path("coverage/lcov.info") == "LARGE_EVIDENCE"
    assert classify_path(".env") == "PRIVATE_FORBIDDEN"
    assert classify_path("secrets/token.json") == "PRIVATE_FORBIDDEN"
    assert classify_path("assets/private/voice/ref.wav") == "PRIVATE_FORBIDDEN"


def test_progress_ledger_contract_is_compact_and_digest_stable():
    ledger = DevelopmentProgressLedger(
        mission_id="wave-b-g0",
        goal_digest="a" * 64,
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="b" * 40,
        recovery_ref="recovery/dev/wave-b-g0",
        checkpoint_sequence=2,
        plan_steps=["inventory", "pin-actions", "root-suite"],
        completed_steps=["inventory"],
        current_step="pin-actions",
        next_step="root-suite",
        open_blockers=[],
        decisions=[{"id":"d1","decision":"full-sha pins"}],
        rejected_directions=["no blind rerun"],
        known_failures=[],
        validation_state="PARTIAL",
        tests={"targeted":"PASS","affected_subgraph":"NOT_RUN","root":"NOT_RUN"},
        evidence_refs=["git:abc"],
        artifact_refs=[],
        do_not_repeat=["inventory"],
        side_effects={"known_completed":[],"unknown_requires_reconciliation":[]},
    )
    payload = ledger.to_dict()
    validate_ledger(payload)
    assert payload["schema_version"] == "DevelopmentProgressLedger/v1"
    assert ledger_digest(payload) == ledger_digest(json.loads(json.dumps(payload, sort_keys=True)))
    assert "chat_transcript" not in payload
