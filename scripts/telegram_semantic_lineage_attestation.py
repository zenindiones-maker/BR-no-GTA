from __future__ import annotations

from typing import Any

from app.database.telegram_egress_outbox_repository import (
    list_telegram_egress_operations_for_request,
)
from app.database.telegram_semantic_request_repository import (
    list_telegram_semantic_requests_for_artifact,
    list_telegram_semantic_requests_for_source_input,
)
from app.database.telegram_user_input_repository import (
    list_recent_telegram_user_inputs,
)


_FINAL_KINDS = {"FINAL_MESSAGE", "FINAL_EDIT", "FINAL_CHUNK"}


def _final_ops(request_id: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list_telegram_egress_operations_for_request(str(request_id))
        if str(item.get("kind") or "") in _FINAL_KINDS
    ]


def _request_completion_flags(
    request: dict[str, Any],
    final_ops: list[dict[str, Any]],
) -> dict[str, bool]:
    attachment = dict(
        (request.get("context_json") or {}).get("active_attachment_context") or {}
    )
    provider_attempts = [
        dict(item)
        for item in (request.get("provider_attempts") or ())
        if isinstance(item, dict)
    ]
    routing_ids = [
        str(item)
        for item in (request.get("routing_ids") or ())
        if str(item).strip()
    ]
    route_from_attempt = any(
        str(item.get("routing_id") or "").strip()
        for item in provider_attempts
    )
    provider_executed = any(
        str(item.get("status") or "").upper() in {"EXECUTED", "SUCCESS", "COMPLETED"}
        for item in provider_attempts
    )
    canonical_result = request.get("canonical_result_json")
    if not provider_executed and isinstance(canonical_result, dict):
        provider_executed = bool(canonical_result.get("provider"))

    egress_sent = bool(final_ops) and all(
        str(item.get("state") or "") == "SENT"
        for item in final_ops
    )
    receipt = bool(final_ops) and all(
        item.get("telegram_message_id") is not None
        for item in final_ops
    )
    return {
        "delivered": str(request.get("status") or "") == "DELIVERED",
        "context": bool(attachment.get("content")),
        "routing": bool(routing_ids or route_from_attempt),
        "provider": bool(provider_executed),
        "result": bool(
            request.get("canonical_result_ref")
            and isinstance(canonical_result, dict)
        ),
        "egress": egress_sent,
        "receipt": receipt,
    }


def _legacy_requests_for_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    sha = str(document.get("content_sha256") or "").strip().lower()
    note_ref = str(document.get("obsidian_note_ref") or "").strip()
    if not sha or not note_ref:
        return []
    artifact_ref = f"obsidian:{note_ref}"
    return [
        item
        for item in list_telegram_semantic_requests_for_artifact(
            telegram_chat_id=int(document["telegram_chat_id"]),
            artifact_content_sha256=sha,
            artifact_ref=artifact_ref,
            limit=50,
        )
        if item.get("source_attachment_input_id") is None
    ]


def _related_requests(document: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = list_telegram_semantic_requests_for_source_input(
        int(document["id"]),
        limit=50,
    )
    seen = {str(item["request_id"]) for item in explicit}
    result = list(explicit)
    for item in _legacy_requests_for_document(document):
        if str(item["request_id"]) in seen:
            continue
        result.append(item)
        seen.add(str(item["request_id"]))
    return sorted(
        result,
        key=lambda item: (
            int(item.get("telegram_input_id") or 0),
            str(item.get("request_id") or ""),
        ),
    )


def _clip(value: str, max_len: int = 139) -> str:
    text = " ".join(str(value).split())
    return text[:max_len]


def build_lineage_attestations(*, limit: int = 200) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    inputs = list_recent_telegram_user_inputs(limit=max(1, min(int(limit), 500)))
    documents = [
        item
        for item in inputs
        if str(item.get("obsidian_materialization_status") or "") == "MATERIALIZED"
        and str(item.get("content_sha256") or "").strip()
        and str(item.get("obsidian_note_ref") or "").strip()
    ]
    for document in sorted(documents, key=lambda item: int(item["id"])):
        source_id = int(document["id"])
        sha = str(document.get("content_sha256") or "").lower()
        related = _related_requests(document)
        for request in related:
            request_id = str(request.get("request_id") or "")
            question_input = int(request.get("telegram_input_id") or 0)
            final_ops = _final_ops(request_id)
            flags = _request_completion_flags(request, final_ops)
            lineage_ok = bool(
                question_input > 0
                and request_id
                and str(request.get("artifact_content_sha256") or "").lower() == sha
            )
            lineage_description = _clip(
                f"doc={source_id} q={question_input} req={request_id[:12]} "
                f"state={request.get('status') or 'NONE'} sha={sha[:8]}"
            )
            rows.append({
                "context": f"telegram-semantic-lineage-{source_id}",
                "state": "success" if lineage_ok else "failure",
                "description": lineage_description,
            })

            complete = all(flags.values())
            completion_description = _clip(
                f"doc={source_id} q={question_input} delivered={int(flags['delivered'])} "
                f"ctx={int(flags['context'])} route={int(flags['routing'])} "
                f"provider={int(flags['provider'])} result={int(flags['result'])} "
                f"egress={int(flags['egress'])} receipt={int(flags['receipt'])}"
            )
            rows.append({
                "context": f"telegram-semantic-completion-{source_id}",
                "state": "success" if complete else "failure",
                "description": completion_description,
            })
    return rows


def main() -> int:
    for row in build_lineage_attestations():
        print(
            f"{row['context']}|{row['state']}|{row['description']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
