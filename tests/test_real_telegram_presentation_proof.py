from __future__ import annotations

import pytest

from app.database.harness_authorization_repository import get_harness_authorization
from app.services.telegram_harness_service import HarnessReasoningFailure
from scripts import prove_real_telegram_presentation as proof
from scripts import telegram_harness_gateway_v2 as gateway


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


def test_generic_telegram_failure_uses_action_first_harness_presentation():
    presentation = gateway._generic_failure_presentation(
        ValueError("uso: /evidence [telegram_input_id]"),
        command="/evidence",
        telegram_message_id=901,
        telegram_update_id=902,
    )
    assert presentation["mode"] == "ACTION_FIRST"
    assert presentation["canonical_unchanged"] is True
    assert presentation["text"].startswith("❌ FAILED")
    assert "Causa observada: uso: /evidence [telegram_input_id]" in presentation["text"]
    auth = get_harness_authorization(presentation["authorization_id"])
    assert auth is not None
    assert auth["status"] == "consumed"
    assert auth["lineage"]["command"] == "/evidence"
    assert auth["lineage"]["presentation_error"] == "ValueError"
    assert auth["lineage"]["memory_write"] is False
    assert auth["lineage"]["routing_authority"] is False
    assert auth["lineage"]["publication_authority"] is False


def test_reasoning_failure_presentation_preserves_real_telegram_input_lineage():
    exc = HarnessReasoningFailure(
        {
            "provider": "opencode",
            "model": "oc/big-pickle",
            "execution_id": "exec-real-failure",
            "episode_id": "episode-real-failure",
            "failure_memory_id": "memory-real-failure",
            "provider_error": {
                "code": "upstream_http_403",
                "message": "HTTP 403 Forbidden",
            },
        }
    )
    presentation = gateway._reasoning_failure_presentation(
        exc,
        input_record={
            "id": 77,
            "telegram_message_id": 88,
            "telegram_update_id": 99,
            "memory_event_id": 111,
            "classification": "chat",
            "input_kind": "text",
            "source_url": None,
        },
    )
    assert presentation["mode"] == "ACTION_FIRST"
    assert presentation["text"].startswith("❌ FAILED")
    auth = get_harness_authorization(presentation["authorization_id"])
    assert auth is not None
    assert auth["lineage"]["telegram_input_id"] == 77
    assert auth["lineage"]["episode_id"] == "episode-real-failure"
    assert auth["lineage"]["failure_memory_id"] == "memory-real-failure"
