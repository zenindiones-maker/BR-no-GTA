from __future__ import annotations

import io
import json
import urllib.error

import pytest

from scripts.telegram_harness_gateway import (
    TelegramApi,
    TelegramRateLimitError,
)


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_api_root_can_target_loopback_local_bot_api_server():
    api = TelegramApi(
        "123456:test-token",
        api_root="http://127.0.0.1:8081/bot",
    )
    assert api._base_url == "http://127.0.0.1:8081/bot123456:test-token"


def test_api_root_rejects_remote_plaintext():
    with pytest.raises(ValueError, match="REMOTE_PLAINTEXT"):
        TelegramApi(
            "123456:test-token",
            api_root="http://telegram.example.test/bot",
        )


def test_send_preserves_forum_topic_and_reply_lineage(monkeypatch):
    api = TelegramApi("123456:test-token")
    calls = []

    def fake_call(method, payload=None, *, timeout=20):
        calls.append((method, dict(payload or {}), timeout))
        return {"message_id": 77}

    monkeypatch.setattr(api, "call", fake_call)
    result = api.send(
        -100123,
        "resposta",
        message_thread_id=42,
        reply_to_message_id=9001,
    )
    assert result == 77
    assert calls == [
        (
            "sendMessage",
            {
                "chat_id": "-100123",
                "text": "resposta",
                "message_thread_id": "42",
                "reply_parameters": '{"message_id":9001}',
            },
            20,
        )
    ]


def test_http_429_raises_typed_retry_after(monkeypatch):
    api = TelegramApi("123456:test-token")

    payload = {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests",
        "parameters": {"retry_after": 9},
    }

    def fake_urlopen(_request, timeout=20):
        raise urllib.error.HTTPError(
            url="https://api.telegram.org",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(TelegramRateLimitError) as excinfo:
        api.call("sendMessage", {"chat_id": "1", "text": "x"})
    assert excinfo.value.retry_after_seconds == 9
