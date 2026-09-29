from __future__ import annotations

import pytest

from app.services.telegram_transport_contract_service import (
    TELEGRAM_REQUIRED_ALLOWED_UPDATES,
    TelegramTransportContractError,
    build_send_message_payload,
    normalize_bot_api_root,
    parse_retry_after_seconds,
    validate_webhook_secret,
    webhook_health_summary,
)


def test_custom_bot_api_root_rejects_remote_plaintext_but_allows_loopback():
    assert normalize_bot_api_root(None) == "https://api.telegram.org/bot"
    assert normalize_bot_api_root("https://telegram.example.test/bot/") == (
        "https://telegram.example.test/bot"
    )
    assert normalize_bot_api_root("http://127.0.0.1:8081/bot") == (
        "http://127.0.0.1:8081/bot"
    )
    with pytest.raises(TelegramTransportContractError, match="REMOTE_PLAINTEXT"):
        normalize_bot_api_root("http://telegram.example.test/bot")


def test_retry_after_is_parsed_only_from_typed_response_parameters():
    assert parse_retry_after_seconds(
        {"ok": False, "parameters": {"retry_after": 7}}
    ) == 7
    assert parse_retry_after_seconds(
        {"ok": False, "parameters": {"retry_after": "12"}}
    ) == 12
    assert parse_retry_after_seconds({"ok": False}) is None
    assert parse_retry_after_seconds(
        {"ok": False, "parameters": {"retry_after": 0}}
    ) is None


def test_send_payload_preserves_forum_topic_and_reply_lineage():
    payload = build_send_message_payload(
        chat_id=-100123,
        text="Resposta governada.",
        message_thread_id=42,
        reply_to_message_id=9001,
    )
    assert payload["chat_id"] == "-100123"
    assert payload["message_thread_id"] == "42"
    assert payload["reply_parameters"] == '{"message_id":9001}'
    assert payload["text"] == "Resposta governada."


def test_webhook_secret_is_fail_closed_and_constant_contract():
    expected = "BRGTA_webhook_secret_123"
    assert validate_webhook_secret(expected, expected) is True
    assert validate_webhook_secret(expected, "wrong") is False
    assert validate_webhook_secret(expected, "") is False
    with pytest.raises(TelegramTransportContractError, match="SECRET_REQUIRED"):
        validate_webhook_secret("", expected)


def test_required_update_subscription_covers_human_control_surface():
    assert TELEGRAM_REQUIRED_ALLOWED_UPDATES == (
        "message",
        "edited_message",
        "callback_query",
        "my_chat_member",
    )


def test_webhook_health_surfaces_backlog_and_delivery_errors_without_tokens():
    health = webhook_health_summary(
        {
            "url": "https://bot.example.test/telegram/webhook",
            "pending_update_count": 3,
            "last_error_date": 123,
            "last_error_message": "connection reset",
            "max_connections": 16,
            "allowed_updates": ["message", "callback_query"],
        }
    )
    assert health["mode"] == "WEBHOOK"
    assert health["configured"] is True
    assert health["pending_update_count"] == 3
    assert health["last_error_present"] is True
    assert health["healthy"] is False
    assert "bot_token" not in str(health).casefold()
