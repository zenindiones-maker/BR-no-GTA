from __future__ import annotations

from scripts.telegram_harness_gateway import (
    TelegramProgressReporter,
    _chat_reply,
    _verify_attachment_remote,
)


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
    assert text.startswith("WAITING_FOR_HUMAN=YES REVIEW_TARGET=SCRIPT")
    assert "Preciso da sua aprovação" in text


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
