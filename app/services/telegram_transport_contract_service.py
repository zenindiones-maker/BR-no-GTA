from __future__ import annotations

import hmac
import json
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse


DEFAULT_TELEGRAM_BOT_API_ROOT = "https://api.telegram.org/bot"
TELEGRAM_REQUIRED_ALLOWED_UPDATES = (
    "message",
    "edited_message",
    "callback_query",
    "my_chat_member",
)


class TelegramTransportContractError(ValueError):
    pass


def normalize_bot_api_root(raw: str | None) -> str:
    value = str(raw or "").strip() or DEFAULT_TELEGRAM_BOT_API_ROOT
    value = value.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TelegramTransportContractError("TELEGRAM_BOT_API_ROOT_INVALID")

    host = (parsed.hostname or "").casefold()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme == "http" and not loopback:
        raise TelegramTransportContractError(
            "TELEGRAM_BOT_API_REMOTE_PLAINTEXT_FORBIDDEN"
        )

    normalized_path = parsed.path.rstrip("/")
    if not normalized_path.endswith("/bot") and normalized_path != "bot":
        # A custom local server may be reverse-proxied under a prefix; require
        # the caller to include the Bot API /bot boundary explicitly.
        if value != DEFAULT_TELEGRAM_BOT_API_ROOT:
            raise TelegramTransportContractError(
                "TELEGRAM_BOT_API_ROOT_MUST_END_IN_BOT"
            )

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            normalized_path,
            "",
            "",
            "",
        )
    ).rstrip("/")


def parse_retry_after_seconds(payload: Mapping[str, Any] | None) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    parameters = payload.get("parameters")
    if not isinstance(parameters, Mapping):
        return None
    raw = parameters.get("retry_after")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def build_send_message_payload(
    *,
    chat_id: int,
    text: str,
    message_thread_id: int | None = None,
    reply_to_message_id: int | None = None,
) -> dict[str, str]:
    rendered = str(text or "")
    if not rendered:
        raise TelegramTransportContractError("TELEGRAM_MESSAGE_TEXT_REQUIRED")

    payload: dict[str, str] = {
        "chat_id": str(int(chat_id)),
        "text": rendered,
    }
    if message_thread_id is not None:
        thread_id = int(message_thread_id)
        if thread_id <= 0:
            raise TelegramTransportContractError(
                "TELEGRAM_MESSAGE_THREAD_ID_INVALID"
            )
        payload["message_thread_id"] = str(thread_id)
    if reply_to_message_id is not None:
        reply_id = int(reply_to_message_id)
        if reply_id <= 0:
            raise TelegramTransportContractError(
                "TELEGRAM_REPLY_MESSAGE_ID_INVALID"
            )
        payload["reply_parameters"] = json.dumps(
            {"message_id": reply_id},
            separators=(",", ":"),
        )
    return payload


def validate_webhook_secret(expected: str, observed: str | None) -> bool:
    expected_value = str(expected or "")
    if not expected_value:
        raise TelegramTransportContractError(
            "TELEGRAM_WEBHOOK_SECRET_REQUIRED"
        )
    observed_value = str(observed or "")
    if not observed_value:
        return False
    return hmac.compare_digest(expected_value, observed_value)


def webhook_health_summary(info: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(info or {})
    url = str(payload.get("url") or "").strip()
    pending = max(0, int(payload.get("pending_update_count") or 0))
    last_error_message = str(payload.get("last_error_message") or "").strip()
    last_error_date = payload.get("last_error_date")
    last_error_present = bool(last_error_message or last_error_date)
    configured = bool(url)

    return {
        "schema": "TelegramWebhookHealth/v1",
        "mode": "WEBHOOK" if configured else "LONG_POLLING",
        "configured": configured,
        "pending_update_count": pending,
        "last_error_present": last_error_present,
        "last_error_date": last_error_date,
        "max_connections": payload.get("max_connections"),
        "allowed_updates": tuple(payload.get("allowed_updates") or ()),
        "healthy": configured and pending == 0 and not last_error_present,
    }
