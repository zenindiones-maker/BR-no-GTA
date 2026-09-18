from __future__ import annotations

import pytest

from scripts import prove_real_telegram_presentation as proof


def test_source_selection_requires_resolved_url_and_editorial_signal(monkeypatch):
    rows = [
        {"id": 1, "source_url": "https://failed.example"},
        {"id": 2, "source_url": "https://resolved.example"},
    ]
    monkeypatch.setattr(proof, "list_recent_telegram_user_inputs", lambda limit=300: rows)
    monkeypatch.setattr(
        proof,
        "get_source_candidate_by_input",
        lambda input_id: {
            "candidate_id": f"candidate-{input_id}",
            "source_content_resolution": "FAIL" if input_id == 1 else "PASS",
        },
    )
    monkeypatch.setattr(
        proof,
        "get_editorial_signal_by_candidate",
        lambda candidate_id: {"signal_id": "signal-2"} if candidate_id == "candidate-2" else None,
    )

    assert proof._find_source_input(None)["id"] == 2
    assert proof._find_failed_source_input(None)["id"] == 1


def test_explicit_source_and_failure_ids_fail_closed_on_wrong_resolution(monkeypatch):
    monkeypatch.setattr(
        proof,
        "get_telegram_user_input",
        lambda input_id: {"id": input_id, "source_url": "https://example.invalid"},
    )
    monkeypatch.setattr(
        proof,
        "get_source_candidate_by_input",
        lambda input_id: {
            "candidate_id": f"candidate-{input_id}",
            "source_content_resolution": "FAIL",
        },
    )

    with pytest.raises(ValueError, match="not a successfully resolved source"):
        proof._find_source_input(7)
    assert proof._find_failed_source_input(7)["id"] == 7


def test_evidence_proof_requires_real_consumed_technical_full_command(monkeypatch):
    monkeypatch.setattr(
        proof,
        "list_recent_harness_authorizations",
        lambda limit=500: [
            {
                "authorization_id": "wrong-mode",
                "subject": "capability:human.presentation.action-first",
                "status": "consumed",
                "lineage": {
                    "telegram_input_id": 42,
                    "audit_command": "/evidence",
                    "presentation_mode": "ACTION_FIRST",
                    "surface": "telegram",
                },
            },
            {
                "authorization_id": "real-evidence",
                "subject": "capability:human.presentation.action-first",
                "status": "consumed",
                "lineage": {
                    "telegram_input_id": 42,
                    "audit_command": "/evidence",
                    "presentation_mode": "TECHNICAL_FULL",
                    "surface": "telegram",
                    "canonical_sha256": "a" * 64,
                },
            },
        ],
    )

    auth = proof._find_evidence_authorization(42)
    assert auth["authorization_id"] == "real-evidence"


def test_evidence_proof_rejects_absent_real_command(monkeypatch):
    monkeypatch.setattr(proof, "list_recent_harness_authorizations", lambda limit=500: [])
    with pytest.raises(RuntimeError, match="no real /evidence presentation authorization"):
        proof._find_evidence_authorization(42)
