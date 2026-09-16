from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.database.memory_claim_evidence_repository import (
    insert_memory_claim_evidence,
    list_memory_claim_evidence_for_event,
)
from app.database.memory_claim_repository import (
    find_memory_claim_by_canonical_key,
    insert_memory_claim,
)
from app.database.memory_event_repository import insert_memory_event
from app.database.memory_repository import find_memory_by_source
from app.database.telegram_user_input_repository import (
    get_telegram_user_input_by_message,
    list_recent_telegram_user_inputs,
    upsert_telegram_user_input,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.memory_claim_evidence_service import create_memory_claim_evidence
from app.services.memory_claim_service import create_memory_claim
from app.services.memory_consolidation_persistence_service import consolidate_and_persist_claim
from app.services.memory_event_service import create_memory_event


TELEGRAM_INPUT_CAPABILITY_ID = "telegram.input.ingest"
TELEGRAM_INPUT_EXECUTOR_BINDING = (
    "app.services.telegram_learning_service.execute_telegram_input_ingestion_capability"
)

_LEARNING_CLASSES = {
    "idea",
    "theme",
    "news",
    "knowledge_note",
    "reference_media",
    "channel_standard",
    "brand_asset",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def classify_telegram_input(
    text: str,
    *,
    has_attachment: bool = False,
    classification_override: str | None = None,
) -> str:
    if classification_override is not None:
        return str(classification_override).strip().lower()

    normalized = _fold(text).strip()
    if any(
        term in normalized
        for term in (
            "padrao do canal",
            "todos os videos",
            "todo video",
            "sempre usar",
            "sempre use",
            "marca registrada",
            "identidade do canal",
        )
    ):
        return "channel_standard"
    if any(term in normalized for term in ("ideia", "pauta", "video sobre", "video de ")):
        return "idea"
    if any(term in normalized for term in ("tema", "assunto para video", "topico")):
        return "theme"
    if any(term in normalized for term in ("noticia", "reportagem", "news", "fonte")):
        return "news"
    if re.search(r"https?://\S+", text or ""):
        return "news"
    if has_attachment:
        return "reference_media"
    if not normalized or normalized in {"oi", "ola", "eai", "blz", "ok", "valeu", "obrigado"}:
        return "chat"
    if normalized.endswith("?") or normalized.startswith(
        ("como ", "quando ", "onde ", "porque ", "por que ", "qual ", "quais ", "quem ", "o que ")
    ):
        return "question"
    if any(term in normalized for term in ("aprenda", "guarde", "lembre", "informacao", "informação")):
        return "knowledge_note"
    if len(normalized) >= 28:
        return "knowledge_note"
    return "chat"


def _safe_input(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "input_kind": record["input_kind"],
        "text_content": record.get("text_content") or "",
        "telegram_file_unique_id": record.get("telegram_file_unique_id"),
        "file_name": record.get("file_name"),
        "mime_type": record.get("mime_type"),
        "file_size": record.get("file_size"),
        "remote_verified": bool(record.get("remote_verified")),
        "classification": record["classification"],
        "learning_status": record["learning_status"],
        "memory_event_id": record.get("memory_event_id"),
        "claim_id": record.get("claim_id"),
        "memory_id": record.get("memory_id"),
        "created_at": record.get("created_at"),
    }


def list_recent_governed_telegram_inputs(*, limit: int = 20) -> dict[str, Any]:
    rows = list_recent_telegram_user_inputs(limit=limit)
    return {
        "authority": "deepseek_harness",
        "source": "canonical BR SQLite",
        "count": len(rows),
        "inputs": [_safe_input(row) for row in rows],
    }


def _memory_claim_for_input(classification: str, text: str, attachment: dict[str, Any] | None) -> tuple[str, str, float, str]:
    clean = str(text or "").strip()
    name = str((attachment or {}).get("file_name") or "").strip()
    if classification == "channel_standard":
        return (f"Padrão do canal definido pelo usuário: {clean}", "observation", 10.0, "active")
    if classification == "idea":
        return (f"Ideia de vídeo enviada pelo usuário: {clean}", "interpretation", 9.5, "active")
    if classification == "theme":
        return (f"Tema de vídeo sugerido pelo usuário: {clean}", "interpretation", 9.0, "active")
    if classification == "news":
        return (f"Notícia ou fonte enviada pelo usuário para verificação: {clean}", "observation", 4.0, "uncertain")
    if classification == "reference_media":
        description = clean or name or str((attachment or {}).get("telegram_file_unique_id") or "mídia sem legenda")
        return (f"Mídia de referência enviada pelo usuário: {description}", "observation", 7.0, "active")
    if classification == "brand_asset":
        description = clean or name or "ativo de branding"
        return (f"Ativo oficial de branding registrado pelo usuário: {description}", "observation", 10.0, "active")
    return (f"Nota sobre GTA 6 enviada pelo usuário: {clean}", "observation", 6.0, "uncertain")


def _persist_memory_learning(
    *,
    event_id: int,
    classification: str,
    text: str,
    attachment: dict[str, Any] | None,
) -> tuple[int | None, int | None]:
    if classification not in _LEARNING_CLASSES:
        return None, None
    claim_text, claim_type, confidence, status = _memory_claim_for_input(
        classification,
        text,
        attachment,
    )
    claim = create_memory_claim(
        claim=claim_text,
        claim_type=claim_type,
        confidence=confidence,
        status=status,
        scope="gta6",
        extraction_method="telegram_user_ingress",
    )
    existing = find_memory_claim_by_canonical_key(claim.canonical_key)
    if existing is None:
        claim_id = insert_memory_claim(claim)
    else:
        claim_id = int(existing["id"])

    linked = any(
        int(item["claim_id"]) == claim_id
        for item in list_memory_claim_evidence_for_event(event_id)
    )
    if not linked:
        relation = create_memory_claim_evidence(
            claim_id=claim_id,
            event_id=event_id,
            evidence_role="supporting",
            weight=1.0,
        )
        insert_memory_claim_evidence(relation)

    memories = find_memory_by_source(
        source_type="memory_claim",
        source_id=str(claim_id),
    )
    if memories:
        memory_id = int(memories[0]["id"])
    else:
        consolidated = consolidate_and_persist_claim(claim_id)
        memory_id = int(consolidated["memory_id"])
    return claim_id, memory_id


def execute_telegram_input_ingestion_capability(
    *,
    payload: dict[str, Any],
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{TELEGRAM_INPUT_CAPABILITY_ID}",
    )
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("Telegram input routing action mismatch")
    if routing_decision.selected_capability_id != TELEGRAM_INPUT_CAPABILITY_ID:
        raise PermissionError("Telegram input capability mismatch")
    if routing_decision.selected_executor_binding != TELEGRAM_INPUT_EXECUTOR_BINDING:
        raise PermissionError("Telegram input executor escaped Registry binding")
    record = GLOBAL_CAPABILITY_REGISTRY.get(TELEGRAM_INPUT_CAPABILITY_ID)
    if record is None or record.executor_binding != TELEGRAM_INPUT_EXECUTOR_BINDING:
        raise PermissionError("Telegram input Registry binding mismatch")

    user_id = int(payload["telegram_user_id"])
    chat_id = int(payload["telegram_chat_id"])
    message_id = int(payload["telegram_message_id"])
    text = str(payload.get("text") or payload.get("caption") or "").strip()
    attachment = payload.get("attachment") if isinstance(payload.get("attachment"), dict) else None
    classification = classify_telegram_input(
        text,
        has_attachment=attachment is not None,
        classification_override=payload.get("classification_override"),
    )
    if classification not in {
        "chat", "question", "idea", "theme", "news", "knowledge_note",
        "reference_media", "channel_standard", "brand_asset",
    }:
        raise ValueError("Telegram classification is outside the governed allowlist")

    existing = get_telegram_user_input_by_message(
        telegram_chat_id=chat_id,
        telegram_message_id=message_id,
    )
    if existing is not None and existing.get("memory_event_id") is not None:
        consume_harness_authorization(auth)
        return {
            "status": "IDEMPOTENT",
            "authority": auth.issued_by,
            "capability_id": TELEGRAM_INPUT_CAPABILITY_ID,
            "routing_id": routing_decision.routing_id,
            "authorization_id": auth.authorization_id,
            "input": _safe_input(existing),
        }

    remote_verified = bool((attachment or {}).get("remote_verified")) if attachment else False
    if attachment is not None:
        file_id = attachment.get("telegram_file_id")
        unique_id = attachment.get("telegram_file_unique_id")
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError("Telegram attachment file_id is required")
        if not isinstance(unique_id, str) or not unique_id.strip():
            raise ValueError("Telegram attachment file_unique_id is required")
        if not remote_verified:
            raise ValueError("Telegram attachment must be remotely verified before ingestion")

    source_id = f"{chat_id}:{message_id}"
    event_content = text
    if not event_content:
        event_content = (
            f"Telegram {str((attachment or {}).get('media_kind') or 'attachment')} "
            f"{str((attachment or {}).get('file_name') or '').strip()}"
        ).strip()
    event = create_memory_event(
        event_type="telegram_user_input",
        source_type="telegram",
        source_id=source_id,
        content=event_content,
        scope="gta6",
        provenance="telegram_harness_ingress",
        metadata={
            "classification": classification,
            "telegram_user_id": user_id,
            "telegram_chat_id": chat_id,
            "telegram_message_id": message_id,
            "telegram_update_id": payload.get("telegram_update_id"),
            "input_kind": payload.get("input_kind") or ((attachment or {}).get("media_kind") if attachment else "text"),
            "telegram_file_unique_id": (attachment or {}).get("telegram_file_unique_id"),
            "file_name": (attachment or {}).get("file_name"),
            "mime_type": (attachment or {}).get("mime_type"),
            "file_size": (attachment or {}).get("file_size"),
            "remote_verified": remote_verified,
            "routing_id": routing_decision.routing_id,
            "authorization_id": auth.authorization_id,
        },
    )
    event_id = insert_memory_event(event)
    claim_id, memory_id = _persist_memory_learning(
        event_id=event_id,
        classification=classification,
        text=text,
        attachment=attachment,
    )
    learning_status = "learned" if memory_id is not None else "captured"
    if classification == "reference_media" and attachment is not None:
        learning_status = "pending_cloud_analysis" if memory_id is not None else "captured"

    saved = upsert_telegram_user_input(
        telegram_user_id=user_id,
        telegram_chat_id=chat_id,
        telegram_message_id=message_id,
        telegram_update_id=(
            int(payload["telegram_update_id"])
            if payload.get("telegram_update_id") is not None
            else None
        ),
        input_kind=str(payload.get("input_kind") or ((attachment or {}).get("media_kind") if attachment else "text")),
        text_content=text,
        telegram_file_id=(attachment or {}).get("telegram_file_id"),
        telegram_file_unique_id=(attachment or {}).get("telegram_file_unique_id"),
        file_name=(attachment or {}).get("file_name"),
        mime_type=(attachment or {}).get("mime_type"),
        file_size=(attachment or {}).get("file_size"),
        width=(attachment or {}).get("width"),
        height=(attachment or {}).get("height"),
        duration_seconds=(attachment or {}).get("duration_seconds"),
        remote_verified=remote_verified,
        classification=classification,
        learning_status=learning_status,
        memory_event_id=event_id,
        claim_id=claim_id,
        memory_id=memory_id,
        provenance={
            "source": "telegram",
            "routing_id": routing_decision.routing_id,
            "authorization_id": auth.authorization_id,
            "harness_decision_id": auth.harness_decision_id,
            "execution_id": auth.execution_id,
        },
    )
    consume_harness_authorization(auth)

    evidence = CapabilityEvidence(
        capability_id=TELEGRAM_INPUT_CAPABILITY_ID,
        provider=record.provider,
        status="EXECUTED",
        active=True,
        authority=auth.authority,
        authorized_action=auth.authorized_action,
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        result={
            "telegram_input_id": saved["id"],
            "classification": classification,
            "learning_status": learning_status,
            "memory_event_id": event_id,
            "claim_id": claim_id,
            "memory_id": memory_id,
        },
        boundary=record.security_boundary,
    )
    canonical = evidence.to_canonical_result(
        authorization_id=auth.authorization_id,
        routing_id=routing_decision.routing_id,
        executor=TELEGRAM_INPUT_EXECUTOR_BINDING,
        operation="ingest_telegram_user_input",
    )
    return {
        "status": "INGESTED",
        "authority": auth.issued_by,
        "capability_id": TELEGRAM_INPUT_CAPABILITY_ID,
        "routing_id": routing_decision.routing_id,
        "authorization_id": auth.authorization_id,
        "input": _safe_input(saved),
        "canonical_execution_result": canonical.to_dict(),
    }


def ingest_telegram_input_under_harness(payload: dict[str, Any]) -> dict[str, Any]:
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="capture interpret and learn from one paired Telegram user input",
            authorized_action="EXECUTION",
            domain="telegram-ingress",
            required_capability_id=TELEGRAM_INPUT_CAPABILITY_ID,
            required_policy_tags=("telegram", "ingress", "learning"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{TELEGRAM_INPUT_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "ingress": "telegram",
            "telegram_user_id": payload.get("telegram_user_id"),
            "telegram_chat_id": payload.get("telegram_chat_id"),
            "telegram_message_id": payload.get("telegram_message_id"),
        },
    )
    return execute_telegram_input_ingestion_capability(
        payload=payload,
        authorization=authorization,
        routing_decision=routing,
    )
