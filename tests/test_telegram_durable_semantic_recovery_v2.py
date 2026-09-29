from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.ai_provider import AIProviderError, AIResponse
from app.services.harness_ai_provider_service import ResilientHarnessAIProvider
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingRequest
from app.services.telegram_harness_service import _telegram_semantic_routing_request


def test_telegram_semantic_route_delegates_provider_universe_to_harness():
    request = _telegram_semantic_routing_request(
        intent="answer bound attachment question",
        goal_id="telegram:1:2",
        learning_required=True,
    )
    assert request.required_capability_id == "ai.reasoning.text"
    assert request.provider_required is True
    assert request.zero_cost_operation is True
    assert request.fallback_allowed is True
    assert tuple(request.allowed_providers or ()) == ()


def test_resilient_provider_excludes_provider_after_provider_wide_503(monkeypatch):
    import app.services.harness_ai_provider_service as service
    from tests.test_harness_ai_provider_service import _decision

    decisions = [
        _decision("nvidia_nim", "model-a"),
        _decision("tuxevil", "model-b"),
    ]
    requests = []

    def route(request):
        requests.append(request)
        return decisions[len(requests) - 1]

    class Provider503:
        def generate(self, _prompt):
            raise AIProviderError(
                "service unavailable",
                code="service_unavailable",
                retryable=True,
                status_code=503,
            )

    class SuccessProvider:
        def generate(self, _prompt):
            return AIResponse(text="ok", provider="tuxevil", model="model-b")

    providers = [Provider503(), SuccessProvider()]
    monkeypatch.setattr(service, "route_harness_request", route)
    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: (
            decisions[len(requests) - 1].selected_provider,
            providers.pop(0),
        ),
    )
    parent = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        harness_decision_id="decision-provider-wide",
        execution_id="execution-provider-wide",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="provider wide reroute",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=True,
            zero_cost_operation=True,
            learning_required=False,
        ),
        max_attempts=2,
    )
    response = provider.generate("Teste")
    assert response.text == "ok"
    assert requests[1].unavailable_provider_ids == ("nvidia_nim",)
    assert requests[1].exhausted_provider_model_pairs == ()


def test_resilient_provider_maps_transient_budget_exhaustion_to_pool_wait(monkeypatch):
    import app.services.harness_ai_provider_service as service
    from tests.test_harness_ai_provider_service import _decision

    monkeypatch.setattr(
        service,
        "route_harness_request",
        lambda _request: _decision("nvidia_nim", "model-a"),
    )

    class TimeoutProvider:
        def generate(self, _prompt):
            raise AIProviderError("timeout", code="timeout", retryable=True)

    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: ("nvidia_nim", TimeoutProvider()),
    )
    parent = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        harness_decision_id="decision-wait",
        execution_id="execution-wait",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="transient wait",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=True,
            zero_cost_operation=True,
            learning_required=False,
        ),
        max_attempts=1,
    )
    with pytest.raises(AIProviderError) as captured:
        provider.generate("Teste")
    assert captured.value.code == "provider_pool_exhausted"
    assert captured.value.retryable is True


def test_durable_semantic_request_identity_and_jitter_are_deterministic():
    from app.services.telegram_semantic_request_service import (
        build_telegram_semantic_request_id,
        deterministic_retry_delay_seconds,
    )

    lineage = dict(
        telegram_chat_id=-1001,
        telegram_message_id=22,
        human_turn_id=9,
        artifact_content_sha256="a" * 64,
        human_text_sha256="b" * 64,
    )
    first = build_telegram_semantic_request_id(**lineage)
    second = build_telegram_semantic_request_id(**lineage)
    assert first == second
    assert deterministic_retry_delay_seconds(first, 3) == deterministic_retry_delay_seconds(first, 3)
    assert 4.0 <= deterministic_retry_delay_seconds(first, 3) <= 8.0


def test_resilient_provider_tracks_free_quota_exhaustion_separately(monkeypatch):
    import app.services.harness_ai_provider_service as service
    from tests.test_harness_ai_provider_service import _decision

    decisions = [_decision("nvidia_nim", "model-a"), _decision("tuxevil", "model-b")]
    requests = []

    def route(request):
        requests.append(request)
        return decisions[len(requests) - 1]

    class QuotaProvider:
        def generate(self, _prompt):
            raise AIProviderError("quota exhausted", code="quota_exhausted", retryable=True)

    class SuccessProvider:
        def generate(self, _prompt):
            return AIResponse(text="ok", provider="tuxevil", model="model-b")

    providers = [QuotaProvider(), SuccessProvider()]
    monkeypatch.setattr(service, "route_harness_request", route)
    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: (decisions[len(requests)-1].selected_provider, providers.pop(0)),
    )
    parent = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        harness_decision_id="decision-quota",
        execution_id="execution-quota",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="quota reroute",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=True,
            zero_cost_operation=True,
            learning_required=False,
        ),
        max_attempts=2,
    )
    assert provider.generate("Teste").text == "ok"
    assert requests[1].exhausted_free_quota_provider_ids == ("nvidia_nim",)
    assert requests[1].unavailable_provider_ids == ()


def test_semantic_request_is_persisted_idempotently_and_claimed_after_restart():
    from app.database.telegram_semantic_request_repository import (
        claim_due_telegram_semantic_requests,
        get_telegram_semantic_request,
        upsert_telegram_semantic_request,
    )

    kwargs = dict(
        request_id="telegram-semantic-test-1",
        telegram_input_id=107,
        telegram_update_id=9001,
        telegram_message_id=201,
        telegram_chat_id=-100123,
        human_turn_id=44,
        thread_id="thread-1",
        human_identity_id="human-1",
        human_text="O que você entendeu desse arquivo?",
        human_text_sha256="b" * 64,
        resolved_reference="obsidian:Inbox/Telegram/doc.md",
        artifact_ref="obsidian:Inbox/Telegram/doc.md",
        obsidian_note_ref="Inbox/Telegram/doc.md",
        artifact_content_sha256="a" * 64,
        normalization_state="LOCAL_TEXT_NORMALIZED",
        context_digest="c" * 64,
        context_json={"active_attachment_context": {"content": "BR_TELEGRAM_FILE_SENTINEL_7F29"}},
        status="WAITING_FOR_PROVIDER_AVAILABILITY",
        next_attempt_at="2000-01-01T00:00:00+00:00",
        wake_condition="provider-health-or-timer",
    )
    request = upsert_telegram_semantic_request(**kwargs)
    same = upsert_telegram_semantic_request(**kwargs)
    assert request["request_id"] == same["request_id"]

    claimed = claim_due_telegram_semantic_requests(
        lease_owner="gateway-restart",
        lease_seconds=60,
        limit=10,
        now_iso="2026-09-29T22:00:00+00:00",
    )
    assert [item["request_id"] for item in claimed] == ["telegram-semantic-test-1"]
    stored = get_telegram_semantic_request("telegram-semantic-test-1")
    assert stored["status"] == "RUNNING"
    assert stored["lease_owner"] == "gateway-restart"
    assert stored["context_json"]["active_attachment_context"]["content"] == "BR_TELEGRAM_FILE_SENTINEL_7F29"


def test_egress_outbox_is_idempotent_and_ambiguous_send_is_not_retried():
    from app.database.telegram_egress_outbox_repository import (
        get_telegram_egress_operation,
        upsert_telegram_egress_operation,
    )
    from app.services.telegram_egress_outbox_service import deliver_telegram_egress_operation

    operation = upsert_telegram_egress_operation(
        operation_id="egress-1",
        request_id="telegram-semantic-test-1",
        chat_id=-100123,
        reply_to_message_id=201,
        kind="WAIT_MESSAGE",
        sequence_number=0,
        payload_text="aguardando",
    )
    same = upsert_telegram_egress_operation(
        operation_id="egress-1",
        request_id="telegram-semantic-test-1",
        chat_id=-100123,
        reply_to_message_id=201,
        kind="WAIT_MESSAGE",
        sequence_number=0,
        payload_text="aguardando",
    )
    assert operation["operation_id"] == same["operation_id"]

    calls = []

    class AmbiguousApi:
        def send(self, chat_id, text, **kwargs):
            calls.append((chat_id, text))
            raise TimeoutError("timeout after POST boundary")

    result = deliver_telegram_egress_operation(AmbiguousApi(), operation)
    assert result["state"] == "UNKNOWN_REMOTE_STATE"
    assert len(calls) == 1

    result2 = deliver_telegram_egress_operation(AmbiguousApi(), result)
    assert result2["state"] == "UNKNOWN_REMOTE_STATE"
    assert len(calls) == 1
    stored = get_telegram_egress_operation("egress-1")
    assert stored["state"] == "UNKNOWN_REMOTE_STATE"


def test_wait_message_is_edited_to_final_using_persisted_message_id():
    from app.database.telegram_egress_outbox_repository import upsert_telegram_egress_operation
    from app.services.telegram_egress_outbox_service import deliver_telegram_egress_operation

    operation = upsert_telegram_egress_operation(
        operation_id="egress-final-edit",
        request_id="telegram-semantic-test-2",
        chat_id=-100123,
        reply_to_message_id=201,
        kind="FINAL_EDIT",
        sequence_number=0,
        payload_text="Resposta final baseada no arquivo.",
        edit_message_id=777,
    )
    calls = []

    class Api:
        def edit(self, chat_id, message_id, text):
            calls.append((chat_id, message_id, text))

    result = deliver_telegram_egress_operation(Api(), operation)
    assert result["state"] == "SENT"
    assert result["telegram_message_id"] == 777
    assert calls == [(-100123, 777, "Resposta final baseada no arquivo.")]


def test_chat_under_harness_uses_resilient_executor_with_exact_attachment_context(monkeypatch):
    import app.services.telegram_harness_service as service
    from tests.test_harness_ai_provider_service import _decision

    decision = _decision("nvidia_nim", "model-a")
    monkeypatch.setattr(service, "route_harness_request", lambda _request: decision)
    seen = {}

    class FakeResilient:
        last_attempts = [{
            "attempt_index": 0,
            "provider": "nvidia_nim",
            "model": "model-a",
            "status": "EXECUTED",
            "routing_id": decision.routing_id,
        }]
        last_retry_count = 0
        last_performance_metrics = {"provider_chain_attempts": 1}
        last_routing_decision = decision

        def generate(self, prompt):
            seen["prompt"] = prompt
            return AIResponse(
                text="O arquivo contém o sentinel e uma regra operacional.",
                provider="nvidia_nim",
                model="model-a",
            )

    monkeypatch.setattr(
        service,
        "create_resilient_harness_ai_provider",
        lambda **_kwargs: FakeResilient(),
    )
    monkeypatch.setattr(
        service,
        "capture_telegram_reasoning_outcome",
        lambda **_kwargs: {
            "INPUT_MEMORY_CAPTURED": "PASS",
            "EXECUTION_OUTCOME_LEARNED": "PASS",
            "episode": {"episode_id": "episode-test"},
            "failure_memory": None,
            "improvement_mission": None,
        },
    )
    result = service.chat_under_harness(
        "O que você entendeu desse arquivo? Me explique os pontos principais.",
        input_record={
            "id": 107,
            "telegram_chat_id": -100123,
            "telegram_message_id": 201,
            "telegram_update_id": 9001,
            "classification": "question",
        },
        conversation_context={
            "resolved_reference": {
                "reference": "obsidian:Inbox/Telegram/doc.md",
                "basis": "active_artifact",
            },
            "active_attachment_context": {
                "artifact_ref": "obsidian:Inbox/Telegram/doc.md",
                "status": "AVAILABLE",
                "content": "BR_TELEGRAM_FILE_SENTINEL_7F29\nFail closed on missing evidence.",
            },
        },
        skip_fresh_research=True,
    )
    assert "BR_TELEGRAM_FILE_SENTINEL_7F29" in seen["prompt"]
    assert result["answer"].startswith("O arquivo contém")
    assert result["RESILIENT_PROVIDER_EXECUTION"] == "PASS"
    assert result["provider_attempts"][0]["routing_id"] == decision.routing_id


def test_chat_under_harness_transient_pool_exhaustion_is_wait_not_terminal(monkeypatch):
    import app.services.telegram_harness_service as service
    from tests.test_harness_ai_provider_service import _decision

    decision = _decision("nvidia_nim", "model-a")
    monkeypatch.setattr(service, "route_harness_request", lambda _request: decision)

    class Exhausted:
        last_attempts = [{
            "attempt_index": 0,
            "provider": "nvidia_nim",
            "model": "model-a",
            "status": "FAILED",
            "failure_code": "timeout",
            "failure_domain": "MODEL_LOCAL",
            "routing_id": decision.routing_id,
        }]
        last_retry_count = 0
        last_performance_metrics = {"provider_chain_attempts": 1}
        last_routing_decision = decision

        def generate(self, _prompt):
            raise AIProviderError(
                "pool exhausted",
                code="provider_pool_exhausted",
                retryable=True,
            )

    monkeypatch.setattr(
        service,
        "create_resilient_harness_ai_provider",
        lambda **_kwargs: Exhausted(),
    )
    result = service.chat_under_harness(
        "Explique esse arquivo.",
        input_record={
            "id": 108,
            "telegram_chat_id": -100123,
            "telegram_message_id": 202,
            "telegram_update_id": 9002,
            "classification": "question",
        },
        conversation_context={
            "active_attachment_context": {
                "artifact_ref": "obsidian:Inbox/Telegram/doc.md",
                "status": "AVAILABLE",
                "content": "BR_TELEGRAM_FILE_SENTINEL_7F29",
            },
        },
        skip_fresh_research=True,
    )
    assert result["status"] == "WAITING_FOR_PROVIDER_AVAILABILITY"
    assert result["terminal"] is False
    assert result["human_intervention_required"] is False
    assert result["human_retry_required"] is False
    assert result["failure_class"] == "PROVIDER_POOL_EXHAUSTED"


def test_durable_attachment_question_waits_restarts_and_edits_same_message(tmp_path, monkeypatch):
    from app.database.telegram_semantic_request_repository import (
        claim_due_telegram_semantic_requests,
        get_telegram_semantic_request,
        update_telegram_semantic_request,
    )
    from app.database.telegram_user_input_repository import (
        update_telegram_attachment_materialization,
        upsert_telegram_user_input,
    )
    from app.services.telegram_conversation_service import register_telegram_attachment_context
    from app.services.telegram_durable_semantic_service import (
        execute_telegram_semantic_request,
        mark_telegram_semantic_request_ready,
        persist_telegram_semantic_request,
    )

    vault = tmp_path / "vault"
    note = vault / "Inbox/Telegram/doc.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "# Documento\nBR_TELEGRAM_FILE_SENTINEL_7F29\nRegra: fail closed on missing evidence.",
        encoding="utf-8",
    )
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))

    attachment = upsert_telegram_user_input(
        telegram_user_id=77,
        telegram_chat_id=-100123,
        telegram_message_id=100,
        telegram_update_id=8000,
        input_kind="document",
        text_content="",
        classification="reference_media",
        learning_status="captured",
        telegram_file_id="file-1",
        telegram_file_unique_id="unique-1",
        file_name="doc.md",
        mime_type="text/markdown",
        remote_verified=True,
    )
    attachment = update_telegram_attachment_materialization(
        int(attachment["id"]),
        status="MATERIALIZED",
        obsidian_attachment_ref="90-Attachments/Telegram/sha256/aa/source.md",
        obsidian_note_ref="Inbox/Telegram/doc.md",
        content_sha256="a" * 64,
        normalized_markdown_ref="Inbox/Telegram/doc.md",
    )
    register_telegram_attachment_context(
        telegram_user_id=77,
        telegram_chat_id=-100123,
        telegram_chat_type="supergroup",
        telegram_message_id=100,
        input_record=attachment,
        bridge_result={
            "status": "MATERIALIZED",
            "obsidian_note_ref": "Inbox/Telegram/doc.md",
            "content_sha256": "a" * 64,
            "normalization_state": "LOCAL_TEXT_NORMALIZED",
        },
    )

    question = upsert_telegram_user_input(
        telegram_user_id=77,
        telegram_chat_id=-100123,
        telegram_message_id=201,
        telegram_update_id=9001,
        input_kind="text",
        text_content="O que você entendeu desse arquivo? Me explique os pontos principais.",
        classification="question",
        learning_status="captured",
    )
    accepted = persist_telegram_semantic_request(
        telegram_user_id=77,
        telegram_chat_id=-100123,
        telegram_chat_type="supergroup",
        telegram_message_id=201,
        telegram_update_id=9001,
        input_record=question,
        human_text="O que você entendeu desse arquivo? Me explique os pontos principais.",
    )
    duplicate = persist_telegram_semantic_request(
        telegram_user_id=77,
        telegram_chat_id=-100123,
        telegram_chat_type="supergroup",
        telegram_message_id=201,
        telegram_update_id=9001,
        input_record=question,
        human_text="O que você entendeu desse arquivo? Me explique os pontos principais.",
    )
    assert duplicate["request_id"] == accepted["request_id"]
    assert duplicate["human_turn_id"] == accepted["human_turn_id"]
    assert accepted["artifact_content_sha256"] == "a" * 64
    assert "BR_TELEGRAM_FILE_SENTINEL_7F29" in (
        accepted["context_json"]["active_attachment_context"]["content"]
    )

    ready = mark_telegram_semantic_request_ready(accepted["request_id"])
    claimed = claim_due_telegram_semantic_requests(
        lease_owner="gateway-before-crash",
        lease_seconds=60,
        limit=1,
        now_iso="2030-01-01T00:00:00+00:00",
    )
    assert claimed[0]["request_id"] == ready["request_id"]

    class Api:
        def __init__(self):
            self.sends = []
            self.edits = []

        def send(self, chat_id, text, **kwargs):
            self.sends.append((chat_id, text, kwargs))
            return 777

        def edit(self, chat_id, message_id, text):
            self.edits.append((chat_id, message_id, text))

    api = Api()

    def unavailable(_message, **_kwargs):
        return {
            "status": "WAITING_FOR_PROVIDER_AVAILABILITY",
            "terminal": False,
            "human_retry_required": False,
            "provider_attempts": [{
                "provider": "nvidia_nim",
                "model": "model-a",
                "status": "FAILED",
                "failure_code": "timeout",
                "failure_domain": "MODEL_LOCAL",
                "routing_id": "routing-a",
            }],
        }

    waiting = execute_telegram_semantic_request(
        api=api,
        request=claimed[0],
        chat_handler=unavailable,
    )
    assert waiting["status"] == "WAITING_FOR_PROVIDER_AVAILABILITY"
    assert waiting["wait_message_id"] == 777
    assert len(api.sends) == 1
    assert "Você não precisa reenviar nada." in api.sends[0][1]

    # Simulated process crash/restart: make the deterministic wake due and let
    # a different worker owner reclaim the SAME persisted request.
    update_telegram_semantic_request(
        accepted["request_id"],
        status="WAITING_FOR_PROVIDER_AVAILABILITY",
        next_attempt_at="2000-01-01T00:00:00+00:00",
        wake_condition="provider-health-or-deterministic-timer",
        lease_owner=None,
        lease_expiry=None,
    )
    reclaimed = claim_due_telegram_semantic_requests(
        lease_owner="gateway-after-restart",
        lease_seconds=60,
        limit=1,
        now_iso="2030-01-01T00:00:01+00:00",
    )
    assert reclaimed[0]["request_id"] == accepted["request_id"]
    assert reclaimed[0]["human_turn_id"] == accepted["human_turn_id"]
    assert reclaimed[0]["artifact_ref"] == accepted["artifact_ref"]
    assert reclaimed[0]["artifact_content_sha256"] == accepted["artifact_content_sha256"]

    def recovered(message, **kwargs):
        assert "BR_TELEGRAM_FILE_SENTINEL_7F29" in (
            kwargs["conversation_context"]["active_attachment_context"]["content"]
        )
        return {
            "status": "COMPLETED",
            "answer": (
                "O arquivo contém BR_TELEGRAM_FILE_SENTINEL_7F29 e exige "
                "fail closed quando falta evidência."
            ),
            "execution_id": "exec-recovered",
            "provider": "tuxevil",
            "model": "model-b",
            "routing_id": "routing-b",
            "provider_attempts": [{
                "provider": "tuxevil",
                "model": "model-b",
                "status": "EXECUTED",
                "routing_id": "routing-b",
            }],
            "RESILIENT_PROVIDER_EXECUTION": "PASS",
        }

    delivered = execute_telegram_semantic_request(
        api=api,
        request=reclaimed[0],
        chat_handler=recovered,
    )
    assert delivered["status"] == "DELIVERED"
    assert len(api.sends) == 1
    assert api.edits == [(
        -100123,
        777,
        "O arquivo contém BR_TELEGRAM_FILE_SENTINEL_7F29 e exige fail closed quando falta evidência.",
    )]
    stored = get_telegram_semantic_request(accepted["request_id"])
    assert stored["status"] == "DELIVERED"
    assert stored["request_id"] == accepted["request_id"]
    assert stored["human_turn_id"] == accepted["human_turn_id"]
    assert stored["wait_message_id"] == 777


def test_sending_egress_after_process_restart_becomes_unknown_without_resend():
    from app.database.telegram_egress_outbox_repository import (
        update_telegram_egress_operation,
        upsert_telegram_egress_operation,
    )
    from app.services.telegram_egress_outbox_service import deliver_telegram_egress_operation

    op = upsert_telegram_egress_operation(
        operation_id="egress-crash-sending",
        request_id="semantic-crash-sending",
        chat_id=-100123,
        reply_to_message_id=201,
        kind="FINAL_MESSAGE",
        sequence_number=0,
        payload_text="resultado",
    )
    op = update_telegram_egress_operation(
        op["operation_id"],
        state="SENDING",
        increment_attempt=True,
    )
    calls = []

    class Api:
        def send(self, *_args, **_kwargs):
            calls.append("send")
            return 999

    reconciled = deliver_telegram_egress_operation(Api(), op)
    assert reconciled["state"] == "UNKNOWN_REMOTE_STATE"
    assert calls == []


def test_context_bound_request_is_recovered_on_gateway_restart():
    from app.database.telegram_semantic_request_repository import (
        get_telegram_semantic_request,
        promote_context_bound_semantic_requests_for_restart,
        upsert_telegram_semantic_request,
    )

    upsert_telegram_semantic_request(
        request_id="semantic-context-bound-crash",
        telegram_input_id=1,
        telegram_update_id=2,
        telegram_message_id=3,
        telegram_chat_id=-10,
        human_turn_id=4,
        thread_id="thread",
        human_identity_id="human",
        human_text="pergunta",
        human_text_sha256="b" * 64,
        resolved_reference=None,
        artifact_ref=None,
        obsidian_note_ref=None,
        artifact_content_sha256=None,
        normalization_state=None,
        context_digest="c" * 64,
        context_json={},
        status="CONTEXT_BOUND",
    )
    assert promote_context_bound_semantic_requests_for_restart(
        now_iso="2026-09-29T22:10:00+00:00"
    ) == 1
    recovered = get_telegram_semantic_request("semantic-context-bound-crash")
    assert recovered["status"] == "READY"
    assert recovered["wake_condition"] == "gateway-restart-recovery"


def test_result_and_all_egress_intents_are_persisted_atomically():
    from app.database.telegram_egress_outbox_repository import (
        list_telegram_egress_operations_for_request,
        persist_semantic_result_and_egress_operations,
    )
    from app.database.telegram_semantic_request_repository import (
        get_telegram_semantic_request,
        upsert_telegram_semantic_request,
    )

    upsert_telegram_semantic_request(
        request_id="semantic-atomic-result",
        telegram_input_id=1,
        telegram_update_id=2,
        telegram_message_id=3,
        telegram_chat_id=-10,
        human_turn_id=4,
        thread_id="thread",
        human_identity_id="human",
        human_text="pergunta",
        human_text_sha256="b" * 64,
        resolved_reference=None,
        artifact_ref=None,
        obsidian_note_ref=None,
        artifact_content_sha256=None,
        normalization_state=None,
        context_digest="c" * 64,
        context_json={},
        status="RUNNING",
    )
    result = {"status": "COMPLETED", "answer": "abcdef"}
    persisted, operations = persist_semantic_result_and_egress_operations(
        request_id="semantic-atomic-result",
        canonical_result_ref="result:abc",
        canonical_result_json=result,
        operations=[
            {
                "operation_id": "atomic-op-0",
                "chat_id": -10,
                "reply_to_message_id": 3,
                "kind": "FINAL_MESSAGE",
                "sequence_number": 0,
                "payload_text": "abc",
                "edit_message_id": None,
            },
            {
                "operation_id": "atomic-op-1",
                "chat_id": -10,
                "reply_to_message_id": 3,
                "kind": "FINAL_CHUNK",
                "sequence_number": 1,
                "payload_text": "def",
                "edit_message_id": None,
            },
        ],
    )
    assert persisted["status"] == "EGRESS_PENDING"
    assert persisted["canonical_result_json"] == result
    assert [op["state"] for op in operations] == ["PENDING", "PENDING"]
    stored_ops = list_telegram_egress_operations_for_request(
        "semantic-atomic-result"
    )
    assert [op["operation_id"] for op in stored_ops] == ["atomic-op-0", "atomic-op-1"]
    assert get_telegram_semantic_request("semantic-atomic-result")["outbox_ref"] == "atomic-op-0"


def test_long_final_answer_uses_one_durable_operation_per_telegram_effect(
    tmp_path, monkeypatch
):
    from app.database.telegram_semantic_request_repository import (
        claim_due_telegram_semantic_requests,
    )
    from app.database.telegram_user_input_repository import (
        update_telegram_attachment_materialization,
        upsert_telegram_user_input,
    )
    from app.services.telegram_conversation_service import register_telegram_attachment_context
    from app.services.telegram_durable_semantic_service import (
        execute_telegram_semantic_request,
        mark_telegram_semantic_request_ready,
        persist_telegram_semantic_request,
    )

    vault = tmp_path / "vault"
    note = vault / "Inbox/Telegram/long.md"
    note.parent.mkdir(parents=True)
    note.write_text("BR_TELEGRAM_FILE_SENTINEL_7F29", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(vault))
    attachment = upsert_telegram_user_input(
        telegram_user_id=77, telegram_chat_id=-100222, telegram_message_id=300,
        telegram_update_id=9300, input_kind="document", text_content="",
        classification="reference_media", learning_status="captured",
        telegram_file_id="f-long", telegram_file_unique_id="u-long",
        file_name="long.md", mime_type="text/markdown", remote_verified=True,
    )
    attachment = update_telegram_attachment_materialization(
        int(attachment["id"]), status="MATERIALIZED",
        obsidian_attachment_ref="90-Attachments/long.md",
        obsidian_note_ref="Inbox/Telegram/long.md",
        content_sha256="d" * 64,
        normalized_markdown_ref="Inbox/Telegram/long.md",
    )
    register_telegram_attachment_context(
        telegram_user_id=77, telegram_chat_id=-100222,
        telegram_chat_type="supergroup", telegram_message_id=300,
        input_record=attachment,
        bridge_result={
            "status": "MATERIALIZED",
            "obsidian_note_ref": "Inbox/Telegram/long.md",
            "content_sha256": "d" * 64,
            "normalization_state": "LOCAL_TEXT_NORMALIZED",
        },
    )
    q = upsert_telegram_user_input(
        telegram_user_id=77, telegram_chat_id=-100222, telegram_message_id=301,
        telegram_update_id=9301, input_kind="text",
        text_content="Explique esse arquivo?", classification="question",
        learning_status="captured",
    )
    req = persist_telegram_semantic_request(
        telegram_user_id=77, telegram_chat_id=-100222,
        telegram_chat_type="supergroup", telegram_message_id=301,
        telegram_update_id=9301, input_record=q,
        human_text="Explique esse arquivo?",
    )
    mark_telegram_semantic_request_ready(req["request_id"])
    claimed = claim_due_telegram_semantic_requests(
        lease_owner="long-worker", lease_seconds=60, limit=1,
        now_iso="2030-01-01T00:00:00+00:00",
    )[0]

    payload = "X" * 8500
    class Api:
        def __init__(self):
            self.sends = []
        def send(self, chat_id, text, **kwargs):
            assert len(text) <= 4000
            self.sends.append((chat_id, text, kwargs))
            return 1000 + len(self.sends)
        def edit(self, *_args):
            raise AssertionError("no wait message exists")

    api = Api()
    delivered = execute_telegram_semantic_request(
        api=api,
        request=claimed,
        chat_handler=lambda *_args, **_kwargs: {
            "status": "COMPLETED",
            "answer": payload,
            "execution_id": "exec-long",
            "provider": "tuxevil",
            "model": "model-b",
            "routing_id": "routing-long",
            "provider_attempts": [],
        },
    )
    assert delivered["status"] == "DELIVERED"
    assert len(api.sends) == 3
    assert "".join(item[1] for item in api.sends) == payload


def test_gateway_restart_drains_pending_final_egress_without_recomputing_semantics():
    from app.database.telegram_egress_outbox_repository import (
        persist_semantic_result_and_egress_operations,
    )
    from app.database.telegram_semantic_request_repository import (
        get_telegram_semantic_request,
        upsert_telegram_semantic_request,
    )
    from app.services.telegram_durable_semantic_service import (
        drain_pending_telegram_egress_operations,
    )

    upsert_telegram_semantic_request(
        request_id="semantic-pending-egress-restart",
        telegram_input_id=1,
        telegram_update_id=2,
        telegram_message_id=3,
        telegram_chat_id=-100500,
        human_turn_id=4,
        thread_id="thread",
        human_identity_id="human",
        human_text="pergunta",
        human_text_sha256="b" * 64,
        resolved_reference=None,
        artifact_ref=None,
        obsidian_note_ref=None,
        artifact_content_sha256=None,
        normalization_state=None,
        context_digest="c" * 64,
        context_json={},
        status="RUNNING",
    )
    result = {
        "status": "COMPLETED",
        "answer": "resultado persistido antes do crash",
        "execution_id": "exec-before-crash",
        "provider": "tuxevil",
        "model": "model-b",
    }
    persist_semantic_result_and_egress_operations(
        request_id="semantic-pending-egress-restart",
        canonical_result_ref="result:pending",
        canonical_result_json=result,
        operations=[{
            "operation_id": "pending-final-op",
            "chat_id": -100500,
            "reply_to_message_id": 3,
            "kind": "FINAL_MESSAGE",
            "sequence_number": 0,
            "payload_text": result["answer"],
            "edit_message_id": None,
        }],
    )

    calls = []
    class Api:
        def send(self, chat_id, text, **kwargs):
            calls.append((chat_id, text, kwargs))
            return 4321
        def edit(self, *_args):
            raise AssertionError("not an edit")

    recovered = drain_pending_telegram_egress_operations(api=Api(), limit=10)
    assert len(calls) == 1
    assert recovered[-1]["request_id"] == "semantic-pending-egress-restart"
    assert recovered[-1]["status"] == "DELIVERED"
    stored = get_telegram_semantic_request("semantic-pending-egress-restart")
    assert stored["status"] == "DELIVERED"
    assert stored["canonical_result_json"] == result


def test_resilient_provider_uses_bound_initial_route_before_any_replan(monkeypatch):
    import app.services.harness_ai_provider_service as service
    from tests.test_harness_ai_provider_service import _decision

    decision = _decision("nvidia_nim", "model-a")
    route_calls = []

    def must_not_route(_request):
        route_calls.append("unexpected")
        raise AssertionError("first attempt must use the already-authorized routing decision")

    class SuccessProvider:
        def generate(self, _prompt):
            return AIResponse(text="ok", provider="nvidia_nim", model="model-a")

    monkeypatch.setattr(service, "route_harness_request", must_not_route)
    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: ("nvidia_nim", SuccessProvider()),
    )
    parent = issue_harness_authorization(
        authorized_action=decision.authorized_action,
        subject="provider:nvidia_nim",
        harness_decision_id="decision-initial-route",
        execution_id="execution-initial-route",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="bound first route",
            authorized_action=decision.authorized_action,
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=True,
            zero_cost_operation=True,
            learning_required=False,
        ),
        initial_routing_decision=decision,
        max_attempts=2,
    )
    assert provider.generate("Teste").text == "ok"
    assert route_calls == []
    assert provider.last_routing_decision.routing_id == decision.routing_id


def test_auth_failure_excludes_failed_provider_and_reroutes(monkeypatch):
    import app.services.harness_ai_provider_service as service
    from tests.test_harness_ai_provider_service import _decision

    decisions = [
        _decision("nvidia_nim", "model-a"),
        _decision("tuxevil", "model-b"),
    ]
    requests = []

    def route(request):
        requests.append(request)
        return decisions[len(requests) - 1]

    class AuthFailureProvider:
        def generate(self, _prompt):
            raise AIProviderError(
                "authentication failed",
                code="authentication_failed",
                retryable=False,
                status_code=401,
            )

    class SuccessProvider:
        def generate(self, _prompt):
            return AIResponse(text="ok", provider="tuxevil", model="model-b")

    providers = [AuthFailureProvider(), SuccessProvider()]
    monkeypatch.setattr(service, "route_harness_request", route)
    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: (
            decisions[len(requests)-1].selected_provider,
            providers.pop(0),
        ),
    )
    parent = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        harness_decision_id="decision-auth-reroute",
        execution_id="execution-auth-reroute",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="auth provider reroute",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=True,
            zero_cost_operation=True,
            learning_required=False,
        ),
        max_attempts=2,
    )
    assert provider.generate("Teste").text == "ok"
    assert requests[1].unavailable_provider_ids == ("nvidia_nim",)
    assert provider.last_attempts[0]["failure_domain"] == "PROVIDER_AUTH"


def test_sqlite_concurrent_semantic_claim_has_exactly_one_winner():
    import threading
    from app.database.telegram_semantic_request_repository import (
        claim_due_telegram_semantic_requests,
        upsert_telegram_semantic_request,
    )

    upsert_telegram_semantic_request(
        request_id="semantic-concurrent-claim",
        telegram_input_id=1,
        telegram_update_id=2,
        telegram_message_id=3,
        telegram_chat_id=-100700,
        human_turn_id=4,
        thread_id="thread",
        human_identity_id="human",
        human_text="pergunta",
        human_text_sha256="b" * 64,
        resolved_reference=None,
        artifact_ref=None,
        obsidian_note_ref=None,
        artifact_content_sha256=None,
        normalization_state=None,
        context_digest="c" * 64,
        context_json={},
        status="READY",
        next_attempt_at="2000-01-01T00:00:00+00:00",
    )
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def worker(owner):
        try:
            barrier.wait()
            claimed = claim_due_telegram_semantic_requests(
                lease_owner=owner,
                lease_seconds=60,
                limit=1,
                now_iso="2030-01-01T00:00:00+00:00",
            )
            results.append((owner, [item["request_id"] for item in claimed]))
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("worker-a",)),
        threading.Thread(target=worker, args=("worker-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    winners = [owner for owner, ids in results if ids == ["semantic-concurrent-claim"]]
    assert len(winners) == 1
    assert sum(1 for _owner, ids in results if ids == []) == 1


def test_atomic_result_outbox_collision_rolls_back_request_transition():
    from app.database.telegram_egress_outbox_repository import (
        persist_semantic_result_and_egress_operations,
        upsert_telegram_egress_operation,
    )
    from app.database.telegram_semantic_request_repository import (
        get_telegram_semantic_request,
        upsert_telegram_semantic_request,
    )

    upsert_telegram_semantic_request(
        request_id="semantic-rollback-result",
        telegram_input_id=1,
        telegram_update_id=2,
        telegram_message_id=3,
        telegram_chat_id=-100701,
        human_turn_id=4,
        thread_id="thread",
        human_identity_id="human",
        human_text="pergunta",
        human_text_sha256="b" * 64,
        resolved_reference=None,
        artifact_ref=None,
        obsidian_note_ref=None,
        artifact_content_sha256=None,
        normalization_state=None,
        context_digest="c" * 64,
        context_json={},
        status="RUNNING",
    )
    upsert_telegram_egress_operation(
        operation_id="collision-existing",
        request_id="semantic-rollback-result",
        chat_id=-100701,
        reply_to_message_id=3,
        kind="FINAL_MESSAGE",
        sequence_number=0,
        payload_text="old-payload",
    )
    with pytest.raises(ValueError, match="identity collision"):
        persist_semantic_result_and_egress_operations(
            request_id="semantic-rollback-result",
            canonical_result_ref="result:new",
            canonical_result_json={"status":"COMPLETED","answer":"new-payload"},
            operations=[{
                "operation_id":"collision-new",
                "chat_id":-100701,
                "reply_to_message_id":3,
                "kind":"FINAL_MESSAGE",
                "sequence_number":0,
                "payload_text":"new-payload",
                "edit_message_id":None,
            }],
        )
    stored = get_telegram_semantic_request("semantic-rollback-result")
    assert stored["status"] == "RUNNING"
    assert stored["canonical_result_json"] is None
    assert stored["canonical_result_ref"] is None


def test_artifact_sha_mismatch_fails_closed_before_provider_call():
    from app.database.telegram_semantic_request_repository import (
        upsert_telegram_semantic_request,
    )
    from app.database.telegram_user_input_repository import (
        update_telegram_attachment_materialization,
        upsert_telegram_user_input,
    )
    from app.services.telegram_durable_semantic_service import (
        execute_telegram_semantic_request,
    )

    attachment = upsert_telegram_user_input(
        telegram_user_id=77,
        telegram_chat_id=-100702,
        telegram_message_id=10,
        telegram_update_id=20,
        input_kind="document",
        text_content="",
        classification="reference_media",
        learning_status="captured",
        telegram_file_id="f",
        telegram_file_unique_id="u",
        file_name="doc.md",
        mime_type="text/markdown",
        remote_verified=True,
    )
    update_telegram_attachment_materialization(
        int(attachment["id"]),
        status="MATERIALIZED",
        obsidian_attachment_ref="90-Attachments/doc.md",
        obsidian_note_ref="Inbox/Telegram/doc.md",
        content_sha256="d" * 64,
        normalized_markdown_ref="Inbox/Telegram/doc.md",
    )
    question = upsert_telegram_user_input(
        telegram_user_id=77,
        telegram_chat_id=-100702,
        telegram_message_id=11,
        telegram_update_id=21,
        input_kind="text",
        text_content="Explique esse arquivo?",
        classification="question",
        learning_status="captured",
    )
    request = upsert_telegram_semantic_request(
        request_id="semantic-artifact-mismatch",
        telegram_input_id=int(question["id"]),
        telegram_update_id=21,
        telegram_message_id=11,
        telegram_chat_id=-100702,
        human_turn_id=99,
        thread_id="thread",
        human_identity_id="human",
        human_text="Explique esse arquivo?",
        human_text_sha256="b" * 64,
        resolved_reference="obsidian:Inbox/Telegram/doc.md",
        artifact_ref="obsidian:Inbox/Telegram/doc.md",
        obsidian_note_ref="Inbox/Telegram/doc.md",
        artifact_content_sha256="a" * 64,
        normalization_state="LOCAL_TEXT_NORMALIZED",
        context_digest="c" * 64,
        context_json={"active_attachment_context":{"content":"sentinel"}},
        status="RUNNING",
    )
    calls = []
    class Api:
        pass
    result = execute_telegram_semantic_request(
        api=Api(),
        request=request,
        chat_handler=lambda *_args, **_kwargs: calls.append("provider") or {},
    )
    assert result["status"] == "FAILED_PERMANENT"
    assert result["failure_class"] == "ARTIFACT_INTEGRITY_MISMATCH"
    assert calls == []


def test_evidence_payload_exposes_durable_semantic_request_and_outbox(monkeypatch):
    from app.database.telegram_egress_outbox_repository import (
        upsert_telegram_egress_operation,
    )
    from app.database.telegram_semantic_request_repository import (
        upsert_telegram_semantic_request,
    )
    from app.database.telegram_user_input_repository import upsert_telegram_user_input
    from scripts import telegram_harness_gateway_v2 as gateway

    record = upsert_telegram_user_input(
        telegram_user_id=77,
        telegram_chat_id=-100700,
        telegram_message_id=701,
        telegram_update_id=9701,
        input_kind="text",
        text_content="Explique o arquivo.",
        classification="question",
        learning_status="captured",
    )
    request = upsert_telegram_semantic_request(
        request_id="semantic-evidence-1",
        telegram_input_id=int(record["id"]),
        telegram_update_id=9701,
        telegram_message_id=701,
        telegram_chat_id=-100700,
        human_turn_id=9,
        thread_id="thread-evidence",
        human_identity_id="human-evidence",
        human_text="Explique o arquivo.",
        human_text_sha256="b" * 64,
        resolved_reference="obsidian:Inbox/Telegram/doc.md",
        artifact_ref="obsidian:Inbox/Telegram/doc.md",
        obsidian_note_ref="Inbox/Telegram/doc.md",
        artifact_content_sha256="a" * 64,
        normalization_state="LOCAL_TEXT_NORMALIZED",
        context_digest="c" * 64,
        context_json={
            "active_attachment_context": {
                "status": "AVAILABLE",
                "artifact_ref": "obsidian:Inbox/Telegram/doc.md",
                "content": "BR_TELEGRAM_FILE_SENTINEL_7F29",
            }
        },
        status="WAITING_FOR_PROVIDER_AVAILABILITY",
        next_attempt_at="2030-01-01T00:00:00+00:00",
        wake_condition="provider-health-or-deterministic-timer",
    )
    op = upsert_telegram_egress_operation(
        operation_id="egress-evidence-wait",
        request_id=request["request_id"],
        chat_id=-100700,
        reply_to_message_id=701,
        kind="WAIT_MESSAGE",
        sequence_number=0,
        payload_text="aguardando",
    )
    payload = gateway._source_evidence_payload(int(record["id"]))
    assert payload["DURABLE_SEMANTIC_REQUEST"] == "PASS"
    assert payload["ATTACHMENT_CONTENT_BOUND"] == "PASS"
    assert payload["HUMAN_RETRY_REQUIRED"] == 0
    semantic = payload["TelegramSemanticReasoningRequest"]
    assert semantic["request_id"] == "semantic-evidence-1"
    assert semantic["artifact_content_sha256"] == "a" * 64
    assert semantic["context_digest"] == "c" * 64
    assert "context_json" not in semantic
    assert payload["TelegramEgressOperations"][0]["operation_id"] == op["operation_id"]
    assert payload["EFFECTIVELY_ONCE_EGRESS"] == "PENDING"


def test_router_exhaustion_after_transient_failure_maps_to_provider_wait(monkeypatch):
    import app.services.harness_ai_provider_service as service
    from tests.test_harness_ai_provider_service import _decision

    first = _decision("nvidia_nim", "model-a")
    route_calls = []

    def route(_request):
        route_calls.append(1)
        if len(route_calls) == 1:
            return first
        raise RuntimeError("no eligible route remains after transient exclusion")

    class Provider503:
        def generate(self, _prompt):
            raise AIProviderError(
                "service unavailable",
                code="service_unavailable",
                retryable=True,
                status_code=503,
            )

    monkeypatch.setattr(service, "route_harness_request", route)
    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: ("nvidia_nim", Provider503()),
    )
    parent = issue_harness_authorization(
        authorized_action=first.authorized_action,
        subject="provider:nvidia_nim",
        harness_decision_id="decision-router-exhausted",
        execution_id="execution-router-exhausted",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="temporary pool exhaust",
            authorized_action=first.authorized_action,
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=True,
            zero_cost_operation=True,
            learning_required=False,
        ),
        max_attempts=3,
    )
    with pytest.raises(AIProviderError) as captured:
        provider.generate("Teste")
    assert captured.value.code == "provider_pool_exhausted"
    assert captured.value.retryable is True
    assert provider.last_attempts[0]["failure_domain"] == "PROVIDER_WIDE"


def test_rate_limit_excludes_rate_limited_provider_before_reroute(monkeypatch):
    import app.services.harness_ai_provider_service as service
    from tests.test_harness_ai_provider_service import _decision

    decisions = [_decision("nvidia_nim", "model-a"), _decision("tuxevil", "model-b")]
    requests = []

    def route(request):
        requests.append(request)
        return decisions[len(requests) - 1]

    class Limited:
        def generate(self, _prompt):
            raise AIProviderError(
                "rate limit",
                code="rate_limited",
                retryable=True,
                status_code=429,
            )

    class Success:
        def generate(self, _prompt):
            return AIResponse(text="ok", provider="tuxevil", model="model-b")

    providers = [Limited(), Success()]
    monkeypatch.setattr(service, "route_harness_request", route)
    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: (
            decisions[len(requests)-1].selected_provider,
            providers.pop(0),
        ),
    )
    parent = issue_harness_authorization(
        authorized_action=decisions[0].authorized_action,
        subject="provider:nvidia_nim",
        harness_decision_id="decision-rate",
        execution_id="execution-rate",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="rate-limit reroute",
            authorized_action=decisions[0].authorized_action,
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=True,
            zero_cost_operation=True,
            learning_required=False,
        ),
        max_attempts=2,
    )
    assert provider.generate("Teste").text == "ok"
    assert requests[1].unavailable_provider_ids == ("nvidia_nim",)


def test_attempt_evidence_contains_authorization_exclusions_and_health_snapshot(monkeypatch):
    import app.services.harness_ai_provider_service as service
    from tests.test_harness_ai_provider_service import _decision

    decision = _decision("nvidia_nim", "model-a")
    class Success:
        def generate(self, _prompt):
            return AIResponse(text="ok", provider="nvidia_nim", model="model-a")

    monkeypatch.setattr(service, "route_harness_request", lambda _request: decision)
    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: ("nvidia_nim", Success()),
    )
    parent = issue_harness_authorization(
        authorized_action=decision.authorized_action,
        subject="provider:nvidia_nim",
        harness_decision_id="decision-evidence",
        execution_id="execution-evidence",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="evidence completeness",
            authorized_action=decision.authorized_action,
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=True,
            zero_cost_operation=True,
            learning_required=False,
            unavailable_provider_ids=("offline-provider",),
            provider_health_snapshot_ref="health:snapshot:1",
            provider_health_snapshot_sha256="f" * 64,
            health_eligible_provider_ids=("nvidia_nim",),
        ),
        max_attempts=1,
    )
    provider.generate("Teste")
    attempt = provider.last_attempts[0]
    assert attempt["authorization_id"]
    assert attempt["unavailable_provider_ids"] == ("offline-provider",)
    assert attempt["provider_health_snapshot_ref"] == "health:snapshot:1"
    assert attempt["provider_health_snapshot_sha256"] == "f" * 64
    assert attempt["health_eligible_provider_ids"] == ("nvidia_nim",)


def test_wait_state_promotes_attempt_exclusions_and_health_to_request_columns():
    from app.database.telegram_semantic_request_repository import (
        get_telegram_semantic_request,
        upsert_telegram_semantic_request,
    )
    from app.services.telegram_durable_semantic_service import _persist_wait_and_deliver

    request = upsert_telegram_semantic_request(
        request_id="semantic-wait-evidence-columns",
        telegram_input_id=1,
        telegram_update_id=2,
        telegram_message_id=3,
        telegram_chat_id=-100800,
        human_turn_id=4,
        thread_id="thread",
        human_identity_id="human",
        human_text="pergunta",
        human_text_sha256="b" * 64,
        resolved_reference=None,
        artifact_ref=None,
        obsidian_note_ref=None,
        artifact_content_sha256=None,
        normalization_state=None,
        context_digest="c" * 64,
        context_json={},
        status="RUNNING",
    )

    class Api:
        def send(self, *_args, **_kwargs):
            return 808
        def edit(self, *_args, **_kwargs):
            raise AssertionError("not expected")

    _persist_wait_and_deliver(
        api=Api(),
        request=request,
        provider_attempts=[{
            "provider": "nvidia_nim",
            "model": "model-a",
            "status": "FAILED",
            "failure_code": "service_unavailable",
            "failure_domain": "PROVIDER_WIDE",
            "routing_id": "route-a",
            "unavailable_provider_ids": ("nvidia_nim",),
            "unavailable_model_ids": ("model-z",),
            "exhausted_provider_model_pairs": (("other", "model-x"),),
            "exhausted_free_quota_provider_ids": ("free-provider",),
            "provider_health_snapshot_ref": "health:1",
            "provider_health_snapshot_sha256": "f" * 64,
        }],
    )
    stored = get_telegram_semantic_request(request["request_id"])
    assert stored["unavailable_provider_ids"] == ["nvidia_nim"]
    assert stored["unavailable_model_ids"] == ["model-z"]
    assert stored["exhausted_provider_model_pairs"] == [["other", "model-x"]]
    assert stored["exhausted_free_quota_provider_ids"] == ["free-provider"]
    assert stored["provider_health_snapshot_ref"] == "health:1"
    assert stored["provider_health_snapshot_sha256"] == "f" * 64


def test_ingress_ack_is_persisted_before_semantic_request_becomes_claimable():
    from pathlib import Path

    text = Path("scripts/telegram_harness_gateway_v2.py").read_text(encoding="utf-8")
    section = text.split("if _is_durable_semantic_question(text):", 1)[1].split(
        "continue", 1
    )[0]
    assert section.index("_save_state(state)") < section.index(
        "mark_telegram_semantic_request_ready"
    )
    assert "semantic_worker = threading.Thread" in text
    assert "target=_semantic_worker_loop" in text


def test_timeout_failure_domain_is_model_local_for_semantic_failover():
    from app.services.telegram_semantic_request_service import (
        classify_semantic_failure_domain,
    )
    assert classify_semantic_failure_domain(
        code="timeout", status_code=None
    ) == "MODEL_LOCAL"
