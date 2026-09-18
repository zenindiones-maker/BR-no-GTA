from __future__ import annotations

from app.database import harness_learning_repository
from app.database.telegram_user_input_repository import upsert_telegram_user_input
from app.services.telegram_review_feedback_service import (
    is_render_review_feedback_message,
    parse_changes_requested,
    record_render_review_feedback,
)


def _input():
    return upsert_telegram_user_input(
        telegram_user_id=111,
        telegram_chat_id=111,
        telegram_message_id=501,
        telegram_update_id=601,
        input_kind="text",
        text_content="CHANGES_REQUESTED: reduzir o ritmo dos cortes no bloco inicial",
        classification="chat",
        learning_status="captured",
        memory_event_id=701,
        provenance={"source": "telegram"},
    )


def _message(text: str, *, review_message_id: int = 401):
    caption = (
        "VIDEO A — REVISÃO — NÃO PUBLICAR\n"
        "RenderJob=920101\n"
        "video_id=920101\n"
        "execution_id=run001-video-a-investigative-v1\n"
        "run_id=35350000000\n"
        "duração=1549.92s\n"
        "versão=investigative-v1\n"
        "HUMAN_EDITORIAL_APPROVAL=PENDING\n"
        "HUMAN_REVIEW_STATE=READY_FOR_HUMAN_REVIEW\n"
        "PUBLICATION_AUTHORITY=NONE"
    )
    return {
        "message_id": 501,
        "text": text,
        "reply_to_message": {
            "message_id": review_message_id,
            "caption": caption,
        },
    }


def test_changes_requested_defaults_to_local_scope():
    assert parse_changes_requested("CHANGES_REQUESTED: ajuste o ritmo") == (
        "LOCAL",
        "ajuste o ritmo",
    )


def test_explicit_broader_scope_must_be_requested():
    assert parse_changes_requested(
        "CHANGES_REQUESTED TASK_CLASS: não repetir esse padrão em renders long-form"
    ) == (
        "TASK_CLASS",
        "não repetir esse padrão em renders long-form",
    )
    assert parse_changes_requested(
        "CHANGES_REQUESTED GLOBAL_CANDIDATE: avaliar esta regra antes de promoção"
    )[0] == "GLOBAL_CANDIDATE"


def test_reply_to_real_review_creates_auditable_human_correction():
    input_record = _input()
    message = _message(input_record["text_content"])

    assert is_render_review_feedback_message(message, input_record["text_content"])
    result = record_render_review_feedback(
        message=message,
        input_record=input_record,
        text=input_record["text_content"],
    )

    assert result["HUMAN_FEEDBACK_INGESTION"] == "PASS"
    assert result["scope"] == "LOCAL"
    assert result["render_job_id"] == 920101
    assert result["video_id"] == 920101
    assert result["execution_id"] == "run001-video-a-investigative-v1"
    assert result["affected_capability"] == "production.render.execute"
    assert result["affected_skill"] == "vedit.longform.render-profile"
    assert result["publication_authority"] == "NONE"

    rows = harness_learning_repository.list_human_corrections(
        affected_capability="production.render.execute",
        affected_skill="vedit.longform.render-profile",
        status="CANDIDATE",
        limit=10,
    )
    assert len(rows) == 1
    correction = rows[0]
    assert correction["correction_id"] == result["correction_id"]
    assert correction["scope"] == "LOCAL"
    assert correction["desired_behavior"] == "reduzir o ritmo dos cortes no bloco inicial"
    assert correction["metadata"]["telegram_review_message_id"] == 401
    assert correction["metadata"]["render_job_id"] == 920101
    assert correction["metadata"]["publication_authority"] == "NONE"
    assert "telegram-review-message:111:401" in correction["evidence_refs"]
    assert "telegram-feedback-message:111:501" in correction["evidence_refs"]


def test_feedback_is_idempotent_for_same_telegram_evidence():
    input_record = _input()
    message = _message(input_record["text_content"])

    first = record_render_review_feedback(
        message=message,
        input_record=input_record,
        text=input_record["text_content"],
    )
    second = record_render_review_feedback(
        message=message,
        input_record=input_record,
        text=input_record["text_content"],
    )
    assert second["correction_id"] == first["correction_id"]

    rows = harness_learning_repository.list_human_corrections(
        affected_capability="production.render.execute",
        affected_skill="vedit.longform.render-profile",
        status="CANDIDATE",
        limit=10,
    )
    assert len(rows) == 1


def test_changes_requested_not_replying_to_review_is_not_ingested_as_correction():
    message = {"message_id": 501, "text": "CHANGES_REQUESTED: ajuste"}
    assert is_render_review_feedback_message(message, message["text"]) is False
