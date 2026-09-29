from __future__ import annotations

from scripts.telegram_semantic_lineage_attestation import build_lineage_attestations


def test_lineage_attestation_is_success_only_for_complete_durable_chain(monkeypatch):
    monkeypatch.setattr(
        "scripts.telegram_semantic_lineage_attestation.list_recent_telegram_user_inputs",
        lambda limit=200: [{
            "id": 113,
            "telegram_chat_id": -1001,
            "telegram_message_id": 602,
            "content_sha256": "7e11d519ebdcbcaa6bf4fb82afe2478b9387e249feed5c65d9daf4a7ff84b131",
            "obsidian_note_ref": "Inbox/Telegram/doc.md",
            "obsidian_materialization_status": "MATERIALIZED",
        }],
    )
    monkeypatch.setattr(
        "scripts.telegram_semantic_lineage_attestation.list_telegram_semantic_requests_for_source_input",
        lambda source_attachment_input_id, limit=50: [],
    )
    monkeypatch.setattr(
        "scripts.telegram_semantic_lineage_attestation.list_telegram_semantic_requests_for_artifact",
        lambda **kwargs: [{
            "request_id": "semantic-abcdef1234567890",
            "telegram_input_id": 114,
            "human_turn_id": 71,
            "source_attachment_input_id": None,
            "artifact_ref": "obsidian:Inbox/Telegram/doc.md",
            "artifact_content_sha256": "7e11d519ebdcbcaa6bf4fb82afe2478b9387e249feed5c65d9daf4a7ff84b131",
            "status": "DELIVERED",
            "context_json": {"active_attachment_context": {"content": "specific document content"}},
            "provider_attempts": [{"status": "EXECUTED", "provider": "tuxevil", "routing_id": "route-1"}],
            "routing_ids": ["route-1"],
            "canonical_result_ref": "result:semantic-1",
            "canonical_result_json": {"status": "COMPLETED", "answer": "grounded"},
        }],
    )
    monkeypatch.setattr(
        "scripts.telegram_semantic_lineage_attestation.list_telegram_egress_operations_for_request",
        lambda request_id: [{
            "kind": "FINAL_MESSAGE",
            "state": "SENT",
            "telegram_message_id": 700,
        }],
    )

    rows = build_lineage_attestations()
    assert len(rows) == 2
    lineage, completion = rows
    assert lineage["context"] == "telegram-semantic-lineage-113"
    assert lineage["state"] == "success"
    assert "q=114" in lineage["description"]
    assert "sha=7e11d519" in lineage["description"]
    assert completion["context"] == "telegram-semantic-completion-113"
    assert completion["state"] == "success"
    assert "ctx=1" in completion["description"]
    assert "route=1" in completion["description"]
    assert "provider=1" in completion["description"]
    assert "result=1" in completion["description"]
    assert "egress=1" in completion["description"]
    assert "receipt=1" in completion["description"]


def test_lineage_attestation_fails_closed_when_egress_receipt_is_missing(monkeypatch):
    monkeypatch.setattr(
        "scripts.telegram_semantic_lineage_attestation.list_recent_telegram_user_inputs",
        lambda limit=200: [{
            "id": 113, "telegram_chat_id": -1001, "telegram_message_id": 602,
            "content_sha256": "a"*64, "obsidian_note_ref": "Inbox/Telegram/doc.md",
            "obsidian_materialization_status": "MATERIALIZED",
        }],
    )
    request = {
        "request_id": "semantic-1", "telegram_input_id": 114, "human_turn_id": 71,
        "source_attachment_input_id": 113,
        "artifact_ref": "obsidian:Inbox/Telegram/doc.md",
        "artifact_content_sha256": "a"*64, "status": "DELIVERED",
        "context_json": {"active_attachment_context": {"content": "content"}},
        "provider_attempts": [{"status": "EXECUTED", "routing_id": "route-1"}],
        "routing_ids": ["route-1"], "canonical_result_ref": "result:1",
        "canonical_result_json": {"status": "COMPLETED"},
    }
    monkeypatch.setattr(
        "scripts.telegram_semantic_lineage_attestation.list_telegram_semantic_requests_for_source_input",
        lambda source_attachment_input_id, limit=50: [request],
    )
    monkeypatch.setattr(
        "scripts.telegram_semantic_lineage_attestation.list_telegram_semantic_requests_for_artifact",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "scripts.telegram_semantic_lineage_attestation.list_telegram_egress_operations_for_request",
        lambda request_id: [{"kind": "FINAL_MESSAGE", "state": "SENT", "telegram_message_id": None}],
    )
    rows = build_lineage_attestations()
    completion = rows[1]
    assert completion["state"] == "failure"
    assert "receipt=0" in completion["description"]
