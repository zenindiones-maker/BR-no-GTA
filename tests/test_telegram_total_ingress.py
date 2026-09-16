from __future__ import annotations

from app.database.memory_event_repository import count_memory_events
from app.services.global_capability_registry import (
    AVAILABLE,
    FUNCTIONAL,
    GLOBAL_CAPABILITY_REGISTRY,
)
from app.services.gta6_knowledge_query_service import query_gta6_knowledge
from app.services.telegram_learning_service import (
    TELEGRAM_INPUT_CAPABILITY_ID,
    TELEGRAM_INPUT_EXECUTOR_BINDING,
    classify_telegram_input,
    ingest_telegram_input_under_harness,
    list_recent_governed_telegram_inputs,
)


def _text_payload(text: str, *, message_id: int = 1) -> dict:
    return {
        "telegram_user_id": 111,
        "telegram_chat_id": 111,
        "telegram_message_id": message_id,
        "telegram_update_id": 1000 + message_id,
        "input_kind": "text",
        "text": text,
    }


def test_registry_contains_total_telegram_ingress_learning_capability():
    record = GLOBAL_CAPABILITY_REGISTRY.get(TELEGRAM_INPUT_CAPABILITY_ID)
    assert record is not None
    assert record.availability == AVAILABLE
    assert record.maturity == FUNCTIONAL
    assert record.allowed_actions == ("EXECUTION",)
    assert record.domain == "telegram-ingress"
    assert record.executor_binding == TELEGRAM_INPUT_EXECUTOR_BINDING
    assert record.fallback_eligibility is False
    assert "sole authority" in record.security_boundary
    assert "publication" in record.security_boundary


def test_classifier_understands_channel_inputs_without_promoting_questions():
    assert classify_telegram_input("Ideia: vídeo sobre as cidades do GTA 6") == "idea"
    assert classify_telegram_input("Tema para vídeo: economia de Vice City") == "theme"
    assert classify_telegram_input("Notícia: https://example.com/gta6") == "news"
    assert classify_telegram_input("Esse é o padrão do canal e deve ser usado em todos os vídeos") == "channel_standard"
    assert classify_telegram_input("Como está o projeto?") == "question"
    assert classify_telegram_input("oi") == "chat"
    assert classify_telegram_input("referência visual", has_attachment=True) == "reference_media"


def test_idea_is_captured_as_event_claim_and_semantic_memory_with_telegram_lineage():
    result = ingest_telegram_input_under_harness(
        _text_payload("Ideia: fazer um vídeo sobre as áreas de Vice City mostradas nos trailers.")
    )

    assert result["status"] == "INGESTED"
    assert result["authority"] == "deepseek_harness"
    assert result["capability_id"] == TELEGRAM_INPUT_CAPABILITY_ID
    item = result["input"]
    assert item["classification"] == "idea"
    assert item["learning_status"] == "learned"
    assert item["memory_event_id"]
    assert item["claim_id"]
    assert item["memory_id"]

    memories = query_gta6_knowledge(query="Vice City trailers", limit=10)
    assert memories
    learned = next(memory for memory in memories if memory.memory_id == item["memory_id"])
    assert "Ideia de vídeo enviada pelo usuário" in learned.content
    assert learned.claims
    assert learned.claims[0].evidences
    evidence = learned.claims[0].evidences[0]
    assert evidence.source_type == "telegram"
    assert evidence.source_id == "111:1"
    assert evidence.provenance == "telegram_harness_ingress"


def test_question_is_preserved_as_evidence_but_not_promoted_to_semantic_memory():
    result = ingest_telegram_input_under_harness(
        _text_payload("Como está o projeto agora?", message_id=2)
    )
    item = result["input"]
    assert item["classification"] == "question"
    assert item["learning_status"] == "captured"
    assert item["memory_event_id"]
    assert item["claim_id"] is None
    assert item["memory_id"] is None


def test_same_telegram_message_is_idempotent_and_does_not_duplicate_memory_events():
    payload = _text_payload("Tema para vídeo: o sistema policial do GTA 6", message_id=3)
    first = ingest_telegram_input_under_harness(payload)
    after_first = count_memory_events()
    second = ingest_telegram_input_under_harness(payload)
    after_second = count_memory_events()

    assert first["status"] == "INGESTED"
    assert second["status"] == "IDEMPOTENT"
    assert after_second == after_first
    assert second["input"]["memory_event_id"] == first["input"]["memory_event_id"]
    assert second["input"]["memory_id"] == first["input"]["memory_id"]


def test_photo_or_video_identity_is_persisted_for_cloud_analysis_without_exposing_file_id():
    payload = _text_payload("Referência visual para futuros vídeos", message_id=4)
    payload.update(
        input_kind="photo",
        attachment={
            "media_kind": "photo",
            "telegram_file_id": "secret-ish-file-id",
            "telegram_file_unique_id": "stable-unique-photo",
            "file_name": "reference.jpg",
            "mime_type": "image/jpeg",
            "file_size": 4321,
            "width": 1280,
            "height": 720,
            "duration_seconds": None,
            "remote_verified": True,
        },
    )

    result = ingest_telegram_input_under_harness(payload)
    item = result["input"]
    assert item["classification"] == "reference_media"
    assert item["learning_status"] == "pending_cloud_analysis"
    assert item["remote_verified"] is True
    assert item["telegram_file_unique_id"] == "stable-unique-photo"
    assert "telegram_file_id" not in item
    assert item["memory_event_id"]
    assert item["memory_id"]

    inbox = list_recent_governed_telegram_inputs(limit=10)
    saved = next(row for row in inbox["inputs"] if row["id"] == item["id"])
    assert saved["telegram_file_unique_id"] == "stable-unique-photo"
    assert "telegram_file_id" not in saved


def test_unverified_attachment_fails_closed_before_any_ingress_persistence():
    payload = _text_payload("Referência visual", message_id=5)
    payload.update(
        input_kind="video",
        attachment={
            "media_kind": "video",
            "telegram_file_id": "file-id",
            "telegram_file_unique_id": "unique-video",
            "mime_type": "video/mp4",
            "remote_verified": False,
        },
    )

    import pytest

    before = count_memory_events()
    with pytest.raises(ValueError, match="remotely verified"):
        ingest_telegram_input_under_harness(payload)
    assert count_memory_events() == before
