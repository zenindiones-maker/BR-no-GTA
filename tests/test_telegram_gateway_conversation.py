from __future__ import annotations

from scripts.telegram_harness_gateway import (
    TelegramProgressReporter,
    _chat_reply,
    _verify_attachment_remote,
)
from scripts import telegram_harness_gateway_v2 as gateway_v2


class FakeTelegramApi:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.calls: list[tuple[str, dict, int]] = []

    def send(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    def call(self, method: str, payload=None, *, timeout: int = 20):
        payload = dict(payload or {})
        self.calls.append((method, payload, timeout))
        if method == "getFile":
            return {"file_path": "documents/sample.bin"}
        return {}


def test_generic_attachment_is_verified_without_downloading_bytes():
    api = FakeTelegramApi()
    verified = _verify_attachment_remote(
        api=api,
        attachment={
            "media_kind": "document",
            "telegram_file_id": "file-id",
            "telegram_file_unique_id": "unique-id",
            "file_name": "roteiro.txt",
            "mime_type": "text/plain",
        },
    )
    assert verified["remote_verified"] is True
    assert verified["remote_file_path"] == "documents/sample.bin"
    assert api.calls == [("getFile", {"file_id": "file-id"}, 20)]


def test_progress_reporter_sends_only_on_meaningful_stage_changes(monkeypatch):
    api = FakeTelegramApi()
    monkeypatch.setenv("TELEGRAM_PROGRESS_MIN_SECONDS", "999")
    reporter = TelegramProgressReporter(api, 7001)
    reporter("RESEARCH", "pesquisando Extended Look")
    reporter("RESEARCH", "18/31 achados analisados")
    reporter("VALIDATION", "validando evidências")
    assert len(api.sent) == 2
    assert "RESEARCH" in api.sent[0][1]
    assert "VALIDATION" in api.sent[1][1]


def test_waiting_for_human_reply_is_explicit_but_still_natural():
    text = _chat_reply(
        {
            "answer": "Revisei o roteiro. Preciso da sua aprovação antes de produzir.",
            "conversation_state": {
                "waiting_for_human": True,
                "pending_human_review": "SCRIPT",
            },
        }
    )
    assert text.startswith("Estou aguardando você sobre SCRIPT.")
    assert "Preciso da sua aprovação" in text
    assert "WAITING_FOR_HUMAN=" not in text


def test_normal_reply_does_not_dump_harness_telemetry():
    text = _chat_reply(
        {
            "answer": "Achei a causa e corrigi o vínculo do resultado.",
            "routing_id": "routing-secret-ish-internal",
            "capability_id": "x",
            "conversation_state": {"waiting_for_human": False},
        }
    )
    assert text == "Achei a causa e corrigi o vínculo do resultado."
    assert "routing_id" not in text



def test_v2_live_gateway_uses_conversation_service_not_direct_reasoning(monkeypatch):
    api = FakeTelegramApi()
    calls = {}

    monkeypatch.setattr(
        gateway_v2,
        "_ingest",
        lambda **kwargs: {
            "input": {
                "id": 901,
                "telegram_chat_id": kwargs["chat_id"],
                "telegram_message_id": kwargs["message"]["message_id"],
            }
        },
    )
    monkeypatch.setattr(
        gateway_v2,
        "_present_chat_v2",
        lambda canonical, input_record=None: {
            "text": canonical.get("answer") or "OK",
            "mode": "ACTION_FIRST",
            "canonical_unchanged": True,
            "authority": "DEEPSEEK_HARNESS",
        },
    )
    monkeypatch.setattr(
        gateway_v2,
        "record_telegram_presentation_audit",
        lambda **kwargs: {
            "telegram_input_id": kwargs["telegram_input_id"],
            "reply_sha256": "test",
        },
    )

    def conversation_service(message, **kwargs):
        calls["message"] = message
        calls["kwargs"] = dict(kwargs)
        kwargs["progress_callback"]("UNDERSTANDING", "resolvendo estado")
        kwargs["progress_callback"]("ROUTING", "roteando sem provider global")
        return {
            "answer": "Estado lido deterministicamente.",
            "intent": "STATUS_REQUEST",
            "plan": {"kind": "STATUS"},
            "conversation_state": {"waiting_for_human": False},
            "canonical_result": {
                "status": "OBSERVED",
                "answer": "Estado lido deterministicamente.",
            },
        }

    monkeypatch.setattr(
        gateway_v2,
        "handle_telegram_conversation",
        conversation_service,
    )

    reply, learned, result = gateway_v2._handle_live_natural_language_message(
        api=api,
        user_id=77,
        chat_id=7007,
        message={"message_id": 88},
        update_id=99,
        text="Onde estamos?",
    )

    assert reply == "Estado lido deterministicamente."
    assert learned["input"]["id"] == 901
    assert result["intent"] == "STATUS_REQUEST"
    assert calls["kwargs"]["telegram_chat_id"] == 7007
    assert calls["kwargs"]["telegram_message_id"] == 88
    assert calls["kwargs"]["input_record"]["id"] == 901
    assert callable(calls["kwargs"]["progress_callback"])
    assert len(api.sent) >= 2
    assert not hasattr(gateway_v2, "chat_under_harness")
