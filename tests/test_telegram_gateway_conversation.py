from __future__ import annotations

import hashlib

from scripts.telegram_harness_gateway import (
    TelegramProgressReporter,
    _chat_reply,
    _verify_attachment_remote,
)
from scripts import telegram_harness_gateway_v2 as gateway_v2
from app.database.telegram_conversation_repository import (
    get_or_create_conversation_state,
    list_recent_telegram_progress_events,
    update_conversation_state,
)
from app.services.harness_learning_service import register_skill_version
from app.services.telegram_ingress_policy_service import (
    parse_governed_telegram_ingress,
)
from app.services.telegram_harness_service import HarnessReasoningFailure
from app.services.opencode_executor_profile_service import (
    CANDIDATE_OPENCODE_EXECUTOR_VERSION,
    OPENCODE_EXECUTOR_SKILL_ID,
    SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    executable_opencode_executor_profile,
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
    update_conversation_state(
        7001,
        execution_status="COMPLETED",
        active_stage="COMPLETE",
        active_blocker="canonical blocker remains untouched",
    )
    before = get_or_create_conversation_state(7001)
    reporter = TelegramProgressReporter(api, 7001)
    reporter("RESEARCH", "pesquisando Extended Look")
    reporter("RESEARCH", "18/31 achados analisados")
    reporter("VALIDATION", "validando evidências")
    after = get_or_create_conversation_state(7001)
    telemetry = list_recent_telegram_progress_events(7001, limit=10)

    assert len(api.sent) == 2
    assert api.sent[0][1] == "pesquisando Extended Look"
    assert api.sent[1][1] == "validando evidências"
    assert "RESEARCH" not in api.sent[0][1]
    assert "VALIDATION" not in api.sent[1][1]
    assert after["execution_status"] == before["execution_status"] == "COMPLETED"
    assert after["active_stage"] == before["active_stage"] == "COMPLETE"
    assert after["active_blocker"] == before["active_blocker"]
    assert {item["stage"] for item in telemetry} >= {"RESEARCH", "VALIDATION"}
    assert all(
        item["metadata"].get("canonical_execution_state_authority") is False
        for item in telemetry
        if item["event_type"] == "PROGRESS"
    )


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
            "answer": "Missão natural roteada pelo ConversationService.",
            "intent": "EXECUTION_REQUEST",
            "plan": {"kind": "CAPABILITY_DISCOVERY"},
            "conversation_state": {"waiting_for_human": False},
            "canonical_result": {
                "status": "OBSERVED",
                "answer": "Missão natural roteada pelo ConversationService.",
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
        text="Analisa esse problema e encontre a ação correta",
    )

    assert reply == "Missão natural roteada pelo ConversationService."
    assert learned["input"]["id"] == 901
    assert result["intent"] == "EXECUTION_REQUEST"
    assert calls["kwargs"]["telegram_user_id"] == 77
    assert calls["kwargs"]["telegram_chat_id"] == 7007
    assert calls["kwargs"]["telegram_chat_type"] == "group"
    assert calls["kwargs"]["telegram_message_id"] == 88
    assert calls["kwargs"]["input_record"]["id"] == 901
    assert callable(calls["kwargs"]["progress_callback"])
    assert len(api.sent) >= 2
    assert not hasattr(gateway_v2, "chat_under_harness")



def test_live_status_ignores_malformed_active_opencode_profile(monkeypatch):
    # Reproduce the exact class of production incident from the real bot:
    # persisted OpenCode profile metadata disagrees with executable code.
    # Provider-free STATUS must not resolve or validate that profile at all.
    profile = executable_opencode_executor_profile(
        SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION
    )
    register_skill_version(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        version=SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
        parent_version=CANDIDATE_OPENCODE_EXECUTOR_VERSION,
        content_ref=profile["content_ref"],
        checksum="0" * 64,
        status="ACTIVE",
        evidence_refs=("telegram-real-checksum-mismatch-regression",),
    )

    api = FakeTelegramApi()
    reply, learned, result = gateway_v2._handle_live_natural_language_message(
        api=api,
        user_id=7701,
        chat_id=7702,
        message={"message_id": 7703},
        update_id=7704,
        text="Onde estamos?",
    )

    assert learned["input"]["classification"] == "question"
    assert result["intent"] == "STATUS_REQUEST"
    assert result["plan"]["kind"] == "STATUS"
    assert result["canonical_result"]["status"] == "OBSERVED"
    assert result["canonical_result"]["control_surface_status"]["provider_independent"] is True
    assert "checksum does not match" not in reply
    assert "FAILED" not in reply



def test_live_status_sends_no_visible_progress_before_final_answer(monkeypatch):
    api = FakeTelegramApi()
    calls = {"provider": 0, "action": 0}

    monkeypatch.setattr(
        gateway_v2,
        "_ingest",
        lambda **kwargs: {
            "input": {
                "id": 9901,
                "telegram_chat_id": kwargs["chat_id"],
                "telegram_message_id": kwargs["message"]["message_id"],
                "classification": "question",
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
            "reply_sha256": "status-no-progress",
        },
    )

    def provider(*_args, **_kwargs):
        calls["provider"] += 1
        raise AssertionError("STATUS must not call ai.reasoning.text")

    def action(*_args, **_kwargs):
        calls["action"] += 1
        raise AssertionError("STATUS must not call Hermes/action executor")

    reply, _learned, result = gateway_v2._handle_live_natural_language_message(
        api=api,
        user_id=9902,
        chat_id=9903,
        chat_type="group",
        message={"message_id": 9904},
        update_id=9905,
        text="Onde estamos?",
        chat_handler=provider,
        action_executor=action,
    )

    assert result["intent"] == "STATUS_REQUEST"
    assert result["plan"]["kind"] == "STATUS"
    assert result["TELEGRAM_USER_ID_PROPAGATED"] == "PASS"
    assert result["TELEGRAM_CHAT_TYPE_PROPAGATED"] == "PASS"
    assert calls == {"provider": 0, "action": 0}
    assert api.sent == []
    assert "UNDERSTANDING" not in reply
    assert reply.strip()



def test_live_status_passes_no_progress_callback_to_conversation_service(monkeypatch):
    api = FakeTelegramApi()
    observed = {}

    monkeypatch.setattr(
        gateway_v2,
        "_ingest",
        lambda **kwargs: {
            "input": {
                "id": 99901,
                "telegram_chat_id": kwargs["chat_id"],
                "telegram_message_id": kwargs["message"]["message_id"],
                "classification": "question",
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
            "reply_sha256": "status-hard-silent",
        },
    )

    def conversation_service(message, **kwargs):
        observed.update(kwargs)
        return {
            "intent": "STATUS_REQUEST",
            "plan": {"kind": "STATUS"},
            "canonical_result": {
                "status": "OBSERVED",
                "answer": "Status final humano.",
            },
            "answer": "Status final humano.",
            "conversation_state": {"waiting_for_human": False},
        }

    reply, _learned, _result = gateway_v2._handle_live_natural_language_message(
        api=api,
        user_id=991,
        chat_id=992,
        chat_type="group",
        message={"message_id": 993},
        update_id=994,
        text="Onde estamos?",
        conversation_handler=conversation_service,
    )

    assert observed["progress_callback"] is None
    assert api.sent == []
    assert reply == "Status final humano."
    assert "UNDERSTANDING" not in reply



def test_governed_ingress_rejects_private_and_accepts_only_authorized_groups():
    state = {
        "chat_id": 11001,
        "allowed_chat_ids": [-22002, -10033003],
    }

    private = parse_governed_telegram_ingress(
        {
            "message": {
                "from": {"id": 77},
                "chat": {"id": 11001, "type": "private"},
                "text": "Onde estamos?",
            }
        },
        allowed_user_id=77,
        state=state,
    )
    group = parse_governed_telegram_ingress(
        {
            "message": {
                "from": {"id": 77},
                "chat": {"id": -22002, "type": "group"},
                "text": "Onde estamos?",
            }
        },
        allowed_user_id=77,
        state=state,
    )
    supergroup = parse_governed_telegram_ingress(
        {
            "message": {
                "from": {"id": 77},
                "chat": {"id": -10033003, "type": "supergroup"},
                "text": "Onde estamos?",
            }
        },
        allowed_user_id=77,
        state=state,
    )
    unauthorized_chat = parse_governed_telegram_ingress(
        {
            "message": {
                "from": {"id": 77},
                "chat": {"id": -44004, "type": "group"},
                "text": "Onde estamos?",
            }
        },
        allowed_user_id=77,
        state=state,
    )
    unauthorized_sender = parse_governed_telegram_ingress(
        {
            "message": {
                "from": {"id": 88},
                "chat": {"id": -22002, "type": "group"},
                "text": "Onde estamos?",
            }
        },
        allowed_user_id=77,
        state=state,
    )

    assert private is None
    assert group is not None and group.accepted is True
    assert group.chat_type == "group"
    assert supergroup is not None and supergroup.accepted is True
    assert supergroup.chat_type == "supergroup"
    assert unauthorized_chat is not None
    assert unauthorized_chat.authorized_sender is True
    assert unauthorized_chat.authorized_chat is False
    assert unauthorized_sender is not None
    assert unauthorized_sender.authorized_sender is False
    assert unauthorized_sender.authorized_chat is False



def test_final_human_response_send_is_logged_only_after_api_success(capsys):
    class SendApi:
        def __init__(self):
            self.calls = []

        def send(self, chat_id, text):
            self.calls.append((chat_id, text))
            return 4242

    api = SendApi()
    reply = "Status humano final."
    message_id = gateway_v2._send_final_human_response(
        api=api,
        chat_id=123,
        reply=reply,
        runtime_revision="deadbeef",
    )
    out = capsys.readouterr().out
    digest = hashlib.sha256(reply.encode("utf-8")).hexdigest()

    assert message_id == 4242
    assert api.calls == [(123, reply)]
    assert "FINAL_HUMAN_RESPONSE_SENT=PASS" in out
    assert "TELEGRAM_SEND_MESSAGE_ID=4242" in out
    assert "SEND_PROCESS_PID=" in out
    assert "SEND_RUNTIME_REVISION=deadbeef" in out
    assert f"REPLY_SHA256={digest}" in out


def test_final_human_response_send_failure_is_explicit(capsys):
    class FailingApi:
        def send(self, _chat_id, _text):
            raise RuntimeError("send failed")

    reply = "Status humano final."
    try:
        gateway_v2._send_final_human_response(
            api=FailingApi(),
            chat_id=123,
            reply=reply,
            runtime_revision="deadbeef",
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("send failure must propagate")
    out = capsys.readouterr().out
    assert "FINAL_HUMAN_RESPONSE_SENT=NO" in out
    assert "SEND_RUNTIME_REVISION=deadbeef" in out
    assert "ERROR=RuntimeError" in out



def test_live_status_group_and_supergroup_return_final_human_answer_without_progress(monkeypatch):
    for chat_type, chat_id in (("group", -77021), ("supergroup", -10077022)):
        api = FakeTelegramApi()
        calls = {"provider": 0, "action": 0}

        monkeypatch.setattr(
            gateway_v2,
            "_ingest",
            lambda **kwargs: {
                "input": {
                    "id": abs(int(kwargs["chat_id"])) + 1000,
                    "telegram_chat_id": kwargs["chat_id"],
                    "telegram_message_id": kwargs["message"]["message_id"],
                    "classification": "question",
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
                "reply_sha256": "group-status-final",
            },
        )

        def provider(*_args, **_kwargs):
            calls["provider"] += 1
            raise AssertionError("group STATUS must not call ai.reasoning.text")

        def action(*_args, **_kwargs):
            calls["action"] += 1
            raise AssertionError("group STATUS must not call Hermes/action executor")

        reply, _learned, result = gateway_v2._handle_live_natural_language_message(
            api=api,
            user_id=77020,
            chat_id=chat_id,
            chat_type=chat_type,
            message={"message_id": 77023},
            update_id=77024,
            text="Onde estamos?",
            chat_handler=provider,
            action_executor=action,
        )

        assert result["intent"] == "STATUS_REQUEST"
        assert result["plan"]["kind"] == "STATUS"
        assert result["TELEGRAM_CHAT_TYPE_PROPAGATED"] == "PASS"
        assert result["human_identity"]["chat_type"] == chat_type
        assert calls == {"provider": 0, "action": 0}
        assert api.sent == []
        assert reply.strip()
        assert "UNDERSTANDING" not in reply



def test_live_status_exact_human_path_sends_one_clean_final_message(monkeypatch):
    api = FakeTelegramApi()

    monkeypatch.setattr(
        gateway_v2,
        "_ingest",
        lambda **kwargs: {
            "input": {
                "id": 12001,
                "telegram_chat_id": kwargs["chat_id"],
                "telegram_message_id": kwargs["message"]["message_id"],
                "classification": "question",
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
            "reply_sha256": "human-status-path",
        },
    )

    def forbidden_provider(*_args, **_kwargs):
        raise AssertionError("Onde estamos? must never call ai.reasoning.text")

    def forbidden_action(*_args, **_kwargs):
        raise AssertionError("Onde estamos? must never dispatch Hermes/action execution")

    reply, _learned, result = gateway_v2._handle_live_natural_language_message(
        api=api,
        user_id=12002,
        chat_id=12003,
        chat_type="group",
        message={"message_id": 12004},
        update_id=12005,
        text="Onde estamos?",
        chat_handler=forbidden_provider,
        action_executor=forbidden_action,
    )

    assert result["intent"] == "STATUS_REQUEST"
    assert api.sent == []
    assert "UNDERSTANDING" not in reply
    assert "REASONING" not in reply
    assert "FAILED" not in reply
    assert "\\n" not in reply

    gateway_v2._send_final_human_response(
        api=api,
        chat_id=12003,
        reply=reply,
        runtime_revision="test-head",
    )
    assert api.sent == [(12003, reply)]


def test_progress_reporter_keeps_internal_control_stages_telemetry_only(monkeypatch):
    api = FakeTelegramApi()
    monkeypatch.setenv("TELEGRAM_PROGRESS_MIN_SECONDS", "5")
    reporter = TelegramProgressReporter(api, 13001)

    reporter("UNDERSTANDING", "resolvendo contexto")
    reporter("ROUTING", "roteando")
    reporter("REASONING", "raciocínio governado")
    assert api.sent == []

    reporter("RESEARCH", "Equipe pesquisando fontes oficiais — 1/3.")
    assert api.sent == [(13001, "Equipe pesquisando fontes oficiais — 1/3.")]



def test_semantic_provider_integrity_failure_is_human_safe():
    exc = HarnessReasoningFailure(
        {
            "provider": "opencode",
            "model": "oc/big-pickle",
            "provider_error": {
                "code": "provider_profile_integrity_mismatch",
                "message": (
                    "active OpenCode executor profile checksum does not match "
                    "executable code"
                ),
                "failure_pattern": "opencode_profile_integrity_mismatch",
                "retryable": False,
            },
            "episode_id": "episode-profile-integrity-test",
            "failure_memory_id": "memory-profile-integrity-test",
            "execution_id": "execution-profile-integrity-test",
        }
    )

    presented = gateway_v2._reasoning_failure_presentation(exc)
    text = presented["text"]

    assert "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE" in text
    assert "checksum does not match executable code" not in text
    assert "active OpenCode executor profile" not in text
    assert "/evidence" in text
    assert presented["mode"] == "ACTION_FIRST"


def test_generic_semantic_provider_boundary_leak_is_sanitized():
    presented = gateway_v2._generic_failure_presentation(
        PermissionError(
            "active OpenCode executor profile checksum does not match executable code"
        ),
        command="natural-language",
        telegram_message_id=70001,
        telegram_update_id=70002,
    )
    text = presented["text"]

    assert "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE" in text
    assert "checksum does not match executable code" not in text
    assert "active OpenCode executor profile" not in text
    assert "/evidence" in text
