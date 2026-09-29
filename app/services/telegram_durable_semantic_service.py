from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Callable

from app.database.telegram_conversation_repository import (
    append_conversation_turn,
    get_conversation_turn_by_message,
    resolve_telegram_human_context,
    update_conversation_state,
)
from app.database.telegram_egress_outbox_repository import (
    claim_pending_telegram_egress_operations,
    list_telegram_egress_operations_for_request,
    persist_semantic_result_and_egress_operations,
    persist_wait_state_and_wait_outbox,
)
from app.database.telegram_semantic_request_repository import (
    claim_due_telegram_semantic_requests,
    get_telegram_semantic_request,
    update_telegram_semantic_request,
    upsert_telegram_semantic_request,
)
from app.database.telegram_user_input_repository import (
    get_telegram_user_input,
    list_recent_telegram_user_inputs,
)
from app.services.telegram_conversation_service import (
    retrieve_conversation_context,
)
from app.services.telegram_egress_outbox_service import (
    deliver_telegram_egress_operation,
)
from app.services.telegram_harness_service import (
    HarnessReasoningFailure,
    chat_under_harness,
)
from app.services.telegram_semantic_request_service import (
    build_telegram_semantic_request_id,
    deterministic_retry_delay_seconds,
)


WAIT_MESSAGE = (
    "⏳ Arquivo preservado e pergunta registrada.\n"
    "O raciocínio está aguardando uma rota semântica elegível.\n"
    "Você não precisa reenviar nada."
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest_json(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _operation_id(request_id: str, kind: str, sequence_number: int) -> str:
    raw = f"TelegramEgressOperation/v1:{request_id}:{kind}:{int(sequence_number)}"
    return "telegram-egress-" + sha256(raw.encode("utf-8")).hexdigest()


def _artifact_lineage(
    *,
    telegram_chat_id: int,
    context: dict[str, Any],
) -> dict[str, Any]:
    resolved = dict(context.get("resolved_reference") or {})
    ref = str(resolved.get("reference") or "").strip()
    attachment = dict(context.get("active_attachment_context") or {})
    note_ref = ref.split(":", 1)[1] if ref.startswith("obsidian:") else None
    source = None
    if note_ref:
        for item in list_recent_telegram_user_inputs(limit=300):
            if int(item.get("telegram_chat_id") or 0) != int(telegram_chat_id):
                continue
            if str(item.get("obsidian_note_ref") or "") == note_ref:
                source = item
                break
    content_sha = str((source or {}).get("content_sha256") or "").strip().lower()
    if ref.startswith("obsidian:") and not content_sha:
        raise ValueError(
            "bound Obsidian attachment lacks canonical content_sha256 lineage"
        )
    source_turn = None
    if source is not None:
        source_turn = get_conversation_turn_by_message(
            telegram_chat_id=int(telegram_chat_id),
            telegram_message_id=int(source["telegram_message_id"]),
            role="HUMAN",
            intent="FILE_SUBMISSION",
        )
    return {
        "resolved_reference": ref or None,
        "artifact_ref": str(attachment.get("artifact_ref") or ref or "").strip() or None,
        "obsidian_note_ref": note_ref,
        "artifact_content_sha256": content_sha,
        "normalization_state": (source or {}).get("normalization_state"),
        "source_attachment_input_id": (
            int(source["id"]) if source is not None else None
        ),
        "source_attachment_turn_id": (
            int(source_turn["turn_id"]) if source_turn is not None else None
        ),
        "source_attachment_message_id": (
            int(source["telegram_message_id"]) if source is not None else None
        ),
    }


def persist_telegram_semantic_request(
    *,
    telegram_user_id: int,
    telegram_chat_id: int,
    telegram_chat_type: str,
    telegram_message_id: int,
    telegram_update_id: int,
    input_record: dict[str, Any],
    human_text: str,
) -> dict[str, Any]:
    identity = resolve_telegram_human_context(
        telegram_user_id=int(telegram_user_id),
        telegram_chat_id=int(telegram_chat_id),
        chat_type=telegram_chat_type,
        project_key="BR-no-GTA",
        allowed=True,
    )
    context = retrieve_conversation_context(
        int(telegram_chat_id),
        current_message=str(human_text),
    )
    lineage = _artifact_lineage(
        telegram_chat_id=int(telegram_chat_id),
        context=context,
    )
    human_turn = append_conversation_turn(
        telegram_chat_id=int(telegram_chat_id),
        telegram_message_id=int(telegram_message_id),
        role="HUMAN",
        text_content=str(human_text),
        intent="QUESTION",
        resolved_reference=lineage["resolved_reference"],
        artifact_ref=lineage["artifact_ref"],
        metadata={
            "telegram_input_id": input_record.get("id"),
            "telegram_update_id": int(telegram_update_id),
            "human_identity_id": identity.get("human_identity_id"),
            "thread_id": identity.get("thread_id"),
            "durable_semantic_request": True,
        },
    )
    # Re-read after the human turn is present so restart execution sees exactly
    # the accepted conversational context, not a later mutable reconstruction.
    context = retrieve_conversation_context(
        int(telegram_chat_id),
        current_message=str(human_text),
    )
    lineage = _artifact_lineage(
        telegram_chat_id=int(telegram_chat_id),
        context=context,
    )
    human_sha = sha256(str(human_text).encode("utf-8")).hexdigest()
    context_digest = _digest_json(context)
    request_id = build_telegram_semantic_request_id(
        telegram_chat_id=int(telegram_chat_id),
        telegram_message_id=int(telegram_message_id),
        human_turn_id=int(human_turn["turn_id"]),
        artifact_content_sha256=lineage["artifact_content_sha256"],
        human_text_sha256=human_sha,
    )
    return upsert_telegram_semantic_request(
        request_id=request_id,
        telegram_input_id=int(input_record["id"]),
        telegram_update_id=int(telegram_update_id),
        telegram_message_id=int(telegram_message_id),
        telegram_chat_id=int(telegram_chat_id),
        human_turn_id=int(human_turn["turn_id"]),
        thread_id=str(identity.get("thread_id") or "") or None,
        human_identity_id=str(identity.get("human_identity_id") or "") or None,
        human_text=str(human_text),
        human_text_sha256=human_sha,
        resolved_reference=lineage["resolved_reference"],
        artifact_ref=lineage["artifact_ref"],
        obsidian_note_ref=lineage["obsidian_note_ref"],
        artifact_content_sha256=lineage["artifact_content_sha256"],
        normalization_state=lineage["normalization_state"],
        source_attachment_input_id=lineage["source_attachment_input_id"],
        source_attachment_turn_id=lineage["source_attachment_turn_id"],
        source_attachment_message_id=lineage["source_attachment_message_id"],
        context_digest=context_digest,
        context_json=context,
        status="CONTEXT_BOUND",
        next_attempt_at=None,
        wake_condition="durable-ingress-ack",
    )


def mark_telegram_semantic_request_ready(request_id: str) -> dict[str, Any]:
    current = get_telegram_semantic_request(request_id)
    if current is None:
        raise ValueError("semantic request not found")
    if current["status"] not in {"RECEIVED", "CONTEXT_BOUND"}:
        return current
    return update_telegram_semantic_request(
        request_id,
        status="READY",
        next_attempt_at=_utcnow(),
        wake_condition="provider-health-or-deterministic-timer",
        lease_owner=None,
        lease_expiry=None,
    )


def _persist_wait_and_deliver(
    *,
    api,
    request: dict[str, Any],
    provider_attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    attempt_count = int(request.get("attempt_count") or 0) + 1
    delay = deterministic_retry_delay_seconds(
        str(request["request_id"]),
        attempt_count,
    )
    next_attempt_at = (
        datetime.now(timezone.utc) + timedelta(seconds=delay)
    ).isoformat()
    attempts = [
        *list(request.get("provider_attempts") or []),
        *list(provider_attempts or []),
    ]
    routing_ids = list(dict.fromkeys([
        *list(request.get("routing_ids") or []),
        *[
            str(item.get("routing_id"))
            for item in provider_attempts
            if item.get("routing_id")
        ],
    ]))
    latest_attempt = dict(provider_attempts[-1]) if provider_attempts else {}
    unavailable_provider_ids = list(dict.fromkeys([
        *list(request.get("unavailable_provider_ids") or []),
        *list(latest_attempt.get("unavailable_provider_ids") or []),
    ]))
    unavailable_model_ids = list(dict.fromkeys([
        *list(request.get("unavailable_model_ids") or []),
        *list(latest_attempt.get("unavailable_model_ids") or []),
    ]))
    exhausted_provider_model_pairs = [
        list(pair)
        for pair in dict.fromkeys(
            tuple(pair)
            for pair in [
                *list(request.get("exhausted_provider_model_pairs") or []),
                *list(latest_attempt.get("exhausted_provider_model_pairs") or []),
            ]
        )
    ]
    exhausted_free_quota_provider_ids = list(dict.fromkeys([
        *list(request.get("exhausted_free_quota_provider_ids") or []),
        *list(latest_attempt.get("exhausted_free_quota_provider_ids") or []),
    ]))
    provider_health_snapshot_ref = (
        latest_attempt.get("provider_health_snapshot_ref")
        or request.get("provider_health_snapshot_ref")
    )
    provider_health_snapshot_sha256 = (
        latest_attempt.get("provider_health_snapshot_sha256")
        or request.get("provider_health_snapshot_sha256")
    )
    op_spec = {
        "operation_id": _operation_id(
            str(request["request_id"]), "WAIT_MESSAGE", 0
        ),
        "chat_id": int(request["telegram_chat_id"]),
        "reply_to_message_id": int(request["telegram_message_id"]),
        "kind": "WAIT_MESSAGE",
        "sequence_number": 0,
        "payload_text": WAIT_MESSAGE,
        "edit_message_id": None,
    }
    waiting, op = persist_wait_state_and_wait_outbox(
        request_id=str(request["request_id"]),
        attempt_count=attempt_count,
        provider_attempts=attempts,
        routing_ids=routing_ids,
        unavailable_provider_ids=unavailable_provider_ids,
        unavailable_model_ids=unavailable_model_ids,
        exhausted_provider_model_pairs=exhausted_provider_model_pairs,
        exhausted_free_quota_provider_ids=exhausted_free_quota_provider_ids,
        provider_health_snapshot_ref=provider_health_snapshot_ref,
        provider_health_snapshot_sha256=provider_health_snapshot_sha256,
        next_attempt_at=next_attempt_at,
        wake_condition="provider-health-or-deterministic-timer",
        operation=op_spec,
    )
    if waiting.get("wait_message_id") is not None:
        return waiting

    delivered = deliver_telegram_egress_operation(api, op)
    if delivered["state"] == "SENT":
        return update_telegram_semantic_request(
            str(waiting["request_id"]),
            status="WAITING_FOR_PROVIDER_AVAILABILITY",
            wait_message_id=int(delivered["telegram_message_id"]),
            next_attempt_at=next_attempt_at,
            wake_condition="provider-health-or-deterministic-timer",
            lease_owner=None,
            lease_expiry=None,
        )
    if delivered["state"] == "UNKNOWN_REMOTE_STATE":
        return update_telegram_semantic_request(
            str(waiting["request_id"]),
            status="UNKNOWN_REMOTE_STATE",
            failure_class="TELEGRAM_EGRESS_UNKNOWN_REMOTE_STATE",
            lease_owner=None,
            lease_expiry=None,
        )
    return waiting


def _split_final_payload(text: str, *, limit: int = 4000) -> list[str]:
    value = str(text or "")
    if not value:
        return [""]
    return [value[index:index + limit] for index in range(0, len(value), limit)]


def _finalize_delivered_semantic_result(request_id: str) -> dict[str, Any]:
    request = get_telegram_semantic_request(request_id)
    if request is None:
        raise ValueError("semantic request not found")
    result = request.get("canonical_result_json")
    if not isinstance(result, dict):
        return request
    operations = list_telegram_egress_operations_for_request(request_id)
    final_operations = [
        item
        for item in operations
        if str(item.get("kind") or "").startswith("FINAL_")
        or str(item.get("kind") or "") == "FINAL_MESSAGE"
    ]
    if not final_operations or any(
        str(item.get("state") or "") != "SENT" for item in final_operations
    ):
        return request
    answer = str(result.get("answer") or "").strip()
    first_message_id = next(
        (
            int(item["telegram_message_id"])
            for item in final_operations
            if item.get("telegram_message_id") is not None
        ),
        None,
    )
    append_conversation_turn(
        telegram_chat_id=int(request["telegram_chat_id"]),
        telegram_message_id=first_message_id,
        role="ASSISTANT",
        text_content=answer,
        intent="QUESTION",
        resolved_reference=request.get("resolved_reference"),
        artifact_ref=request.get("artifact_ref"),
        execution_id=str(result.get("execution_id") or "") or None,
        metadata={
            "request_id": request["request_id"],
            "durable_semantic_result": True,
            "provider": result.get("provider"),
            "model": result.get("model"),
        },
    )
    update_conversation_state(
        int(request["telegram_chat_id"]),
        active_artifact=request.get("artifact_ref"),
        active_stage="COMPLETE",
        active_blocker=None,
        execution_status="COMPLETED",
        waiting_for_human=False,
        pending_question=None,
        last_execution_result=result,
    )
    return update_telegram_semantic_request(
        request["request_id"],
        status="DELIVERED",
        lease_owner=None,
        lease_expiry=None,
    )


def drain_pending_telegram_egress_operations(
    *,
    api,
    limit: int = 50,
    lease_owner: str | None = None,
) -> list[dict[str, Any]]:
    owner = str(
        lease_owner
        or f"telegram-egress:{__import__('os').getpid()}"
    )
    operations = claim_pending_telegram_egress_operations(
        lease_owner=owner,
        lease_seconds=60,
        limit=int(limit),
    )
    results: list[dict[str, Any]] = []
    affected: set[str] = set()
    for operation in operations:
        request_id = str(operation.get("request_id") or "")
        if not request_id:
            continue
        affected.add(request_id)
        request = get_telegram_semantic_request(request_id)
        if request is None or request.get("status") == "DELIVERED":
            continue
        delivered = deliver_telegram_egress_operation(api, operation)
        if delivered["state"] == "UNKNOWN_REMOTE_STATE":
            results.append(
                update_telegram_semantic_request(
                    request_id,
                    status="UNKNOWN_REMOTE_STATE",
                    failure_class="TELEGRAM_EGRESS_UNKNOWN_REMOTE_STATE",
                    lease_owner=None,
                    lease_expiry=None,
                )
            )
            continue
        if (
            delivered["state"] == "SENT"
            and str(delivered.get("kind") or "") == "WAIT_MESSAGE"
            and delivered.get("telegram_message_id") is not None
        ):
            results.append(
                update_telegram_semantic_request(
                    request_id,
                    status="WAITING_FOR_PROVIDER_AVAILABILITY",
                    wait_message_id=int(delivered["telegram_message_id"]),
                    next_attempt_at=request.get("next_attempt_at"),
                    wake_condition=request.get("wake_condition"),
                    lease_owner=None,
                    lease_expiry=None,
                )
            )

    for request_id in sorted(affected):
        current = get_telegram_semantic_request(request_id)
        if current is None:
            continue
        if current["status"] == "EGRESS_PENDING":
            finalized = _finalize_delivered_semantic_result(request_id)
            if finalized["status"] == "DELIVERED":
                results.append(finalized)
    return results


def _persist_result_and_deliver(
    *,
    api,
    request: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    answer = str(result.get("answer") or "").strip()
    if not answer:
        raise ValueError("semantic completion has no human answer")
    result_ref = (
        "telegram-semantic-result-sha256:"
        + _digest_json(result)
    )

    attempts = [
        *list(request.get("provider_attempts") or []),
        *list(result.get("provider_attempts") or []),
    ]
    routing_ids = list(dict.fromkeys([
        *list(request.get("routing_ids") or []),
        *[
            str(item.get("routing_id"))
            for item in (result.get("provider_attempts") or [])
            if item.get("routing_id")
        ],
        *([str(result.get("routing_id"))] if result.get("routing_id") else []),
    ]))
    # Provider evidence is durable before the result/outbox transaction.
    # The canonical result and every external egress intent are persisted atomically below.
    request = update_telegram_semantic_request(
        request["request_id"],
        status="RUNNING",
        attempt_count=int(request.get("attempt_count") or 0) + 1,
        provider_attempts=attempts,
        routing_ids=routing_ids,
        lease_owner=request.get("lease_owner"),
        lease_expiry=request.get("lease_expiry"),
    )

    chunks = _split_final_payload(answer)
    wait_message_id = request.get("wait_message_id")
    operations: list[dict[str, Any]] = []
    for sequence_number, chunk in enumerate(chunks):
        if sequence_number == 0 and wait_message_id is not None:
            kind = "FINAL_EDIT"
            edit_message_id = int(wait_message_id)
        elif sequence_number == 0:
            kind = "FINAL_MESSAGE"
            edit_message_id = None
        else:
            kind = "FINAL_CHUNK"
            edit_message_id = None
        operations.append({
            "operation_id": _operation_id(
                request["request_id"], kind, sequence_number
            ),
            "chat_id": int(request["telegram_chat_id"]),
            "reply_to_message_id": int(request["telegram_message_id"]),
            "kind": kind,
            "sequence_number": sequence_number,
            "payload_text": chunk,
            "edit_message_id": edit_message_id,
        })

    pending, persisted_operations = persist_semantic_result_and_egress_operations(
        request_id=request["request_id"],
        canonical_result_ref=result_ref,
        canonical_result_json=result,
        operations=operations,
    )

    for operation in persisted_operations:
        delivered = deliver_telegram_egress_operation(api, operation)
        if delivered["state"] != "SENT":
            if delivered["state"] == "UNKNOWN_REMOTE_STATE":
                return update_telegram_semantic_request(
                    pending["request_id"],
                    status="UNKNOWN_REMOTE_STATE",
                    failure_class="TELEGRAM_EGRESS_UNKNOWN_REMOTE_STATE",
                    lease_owner=None,
                    lease_expiry=None,
                )
            return get_telegram_semantic_request(pending["request_id"]) or pending

    return _finalize_delivered_semantic_result(pending["request_id"])


def _validate_persisted_artifact_integrity(
    request: dict[str, Any],
) -> bool:
    expected = str(
        request.get("artifact_content_sha256") or ""
    ).strip().lower()
    note_ref = str(request.get("obsidian_note_ref") or "").strip()
    if not expected or not note_ref:
        return True
    for item in list_recent_telegram_user_inputs(limit=500):
        if int(item.get("telegram_chat_id") or 0) != int(
            request["telegram_chat_id"]
        ):
            continue
        if str(item.get("obsidian_note_ref") or "").strip() != note_ref:
            continue
        observed = str(item.get("content_sha256") or "").strip().lower()
        return bool(observed and observed == expected)
    return False


def execute_telegram_semantic_request(
    *,
    api,
    request: dict[str, Any],
    chat_handler: Callable[..., dict[str, Any]] = chat_under_harness,
) -> dict[str, Any]:
    canonical = get_telegram_semantic_request(str(request["request_id"]))
    if canonical is None:
        raise ValueError("semantic request not found")
    if canonical["status"] == "UNKNOWN_REMOTE_STATE":
        return canonical
    if not _validate_persisted_artifact_integrity(canonical):
        return update_telegram_semantic_request(
            canonical["request_id"],
            status="FAILED_PERMANENT",
            failure_class="ARTIFACT_INTEGRITY_MISMATCH",
            lease_owner=None,
            lease_expiry=None,
        )
    input_record = get_telegram_user_input(int(canonical["telegram_input_id"]))
    if input_record is None:
        return update_telegram_semantic_request(
            canonical["request_id"],
            status="FAILED_PERMANENT",
            failure_class="TELEGRAM_INPUT_MISSING",
            lease_owner=None,
            lease_expiry=None,
        )
    try:
        result = chat_handler(
            str(canonical["human_text"]),
            input_record=input_record,
            conversation_context=dict(canonical["context_json"]),
        )
    except HarnessReasoningFailure as exc:
        payload = exc.to_dict()
        error = payload.get("provider_error")
        error = error if isinstance(error, dict) else {}
        return update_telegram_semantic_request(
            canonical["request_id"],
            status="FAILED_PERMANENT",
            failure_class=str(error.get("code") or "SEMANTIC_REASONING_FAILED"),
            provider_attempts=[
                *list(canonical.get("provider_attempts") or []),
                *list(payload.get("provider_attempts") or []),
            ],
            lease_owner=None,
            lease_expiry=None,
        )

    if str(result.get("status") or "").upper() == "WAITING_FOR_PROVIDER_AVAILABILITY":
        return _persist_wait_and_deliver(
            api=api,
            request=canonical,
            provider_attempts=list(result.get("provider_attempts") or []),
        )
    return _persist_result_and_deliver(
        api=api,
        request=canonical,
        result=result,
    )


def drain_due_telegram_semantic_requests(
    *,
    api,
    lease_owner: str,
    limit: int = 8,
    chat_handler: Callable[..., dict[str, Any]] = chat_under_harness,
) -> list[dict[str, Any]]:
    claimed = claim_due_telegram_semantic_requests(
        lease_owner=str(lease_owner),
        lease_seconds=120,
        limit=int(limit),
    )
    return [
        execute_telegram_semantic_request(
            api=api,
            request=request,
            chat_handler=chat_handler,
        )
        for request in claimed
    ]
