from __future__ import annotations

import json
from typing import Any

from app.database.telegram_brand_asset_repository import (
    list_active_brand_assets,
    upsert_active_brand_asset,
)
from app.services.gta6_knowledge_query_service import (
    knowledge_context_to_dict,
    query_gta6_knowledge_context,
)
from app.services.gta6_observation_service import build_gta6_observation
from app.services.harness_ai_provider_service import execute_harness_ai_generation
from app.services.harness_authorization_service import (
    HARNESS_ISSUER,
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


TELEGRAM_ASSET_CAPABILITY_ID = "telegram.asset.register"
TELEGRAM_ASSET_EXECUTOR_BINDING = (
    "app.services.telegram_harness_service.execute_telegram_asset_registration_capability"
)


def _safe_asset(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "asset_type": record["asset_type"],
        "telegram_file_unique_id": record["telegram_file_unique_id"],
        "media_kind": record["media_kind"],
        "file_name": record.get("file_name"),
        "mime_type": record.get("mime_type"),
        "file_size": record.get("file_size"),
        "width": record.get("width"),
        "height": record.get("height"),
        "duration_seconds": record.get("duration_seconds"),
        "telegram_message_id": record["telegram_message_id"],
        "remote_verified": bool(record.get("remote_verified")),
        "active": bool(record.get("active")),
        "created_at": record.get("created_at"),
        "provenance": record.get("provenance") or {},
    }


def list_governed_brand_assets() -> dict[str, Any]:
    assets = [_safe_asset(item) for item in list_active_brand_assets()]
    return {
        "authority": HARNESS_ISSUER,
        "source": "canonical BR SQLite",
        "count": len(assets),
        "assets": assets,
    }


def build_harness_connection_proof() -> dict[str, Any]:
    """Create persisted route/auth evidence without executing a side effect."""
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="prove Telegram conversational ingress is bound to DeepSeek Harness AI reasoning",
            authorized_action="DECISION",
            domain="ai",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"provider:{routing.selected_provider}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_provider": routing.selected_provider,
            "selected_model": routing.selected_model,
            "selected_executor_binding": routing.selected_provider_executor_binding,
            "ingress": "telegram",
            "proof_only": True,
        },
    )
    consume_harness_authorization(authorization)
    observation = build_gta6_observation()
    return {
        "TELEGRAM_HARNESS": "PASS",
        "authority": authorization.issued_by,
        "authorization_id": authorization.authorization_id,
        "authorization_status": "consumed",
        "routing_id": routing.routing_id,
        "selected_capability_id": routing.selected_capability_id,
        "selected_provider": routing.selected_provider,
        "selected_model": routing.selected_model,
        "provider_executor": routing.selected_provider_executor_binding,
        "fallback_occurred": routing.fallback_occurred,
        "zero_cost_operation": bool(routing.policy_metadata.get("zero_cost_operation")),
        "canonical_state_source": observation.get("source_of_truth"),
        "domain": observation.get("domain"),
    }


def _chat_context(message: str) -> dict[str, Any]:
    observation = build_gta6_observation()
    knowledge = query_gta6_knowledge_context(query=message)
    compact_observation = {
        "domain": observation.get("domain"),
        "source_of_truth": observation.get("source_of_truth"),
        "monitor": observation.get("monitor"),
    }
    return {
        "observation": compact_observation,
        "knowledge": knowledge_context_to_dict(knowledge) if knowledge is not None else None,
    }


def chat_under_harness(message: str) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        raise ValueError("Telegram chat message is empty")
    if len(text) > 8000:
        raise ValueError("Telegram chat message is too long")

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="answer one Telegram user message with governed GTA6 reasoning",
            authorized_action="DECISION",
            domain="ai",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    if not routing.selected_provider:
        raise RuntimeError("Harness did not select an AI provider")

    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"provider:{routing.selected_provider}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_provider": routing.selected_provider,
            "selected_model": routing.selected_model,
            "selected_executor_binding": routing.selected_provider_executor_binding,
            "ingress": "telegram",
        },
    )

    context = _chat_context(text)
    prompt = (
        "Você é a interface conversacional do BR-no-GTA subordinada ao DeepSeek Harness. "
        "Responda em português do Brasil, de forma clara e prática. "
        "Você NÃO é uma autoridade paralela e NÃO deve afirmar que executou, publicou, "
        "apagou ou alterou algo apenas por conversa. Ações com efeito colateral continuam "
        "dependendo das capabilities e gates oficiais do Harness. Para publicação pública, "
        "sempre preserve o gate exato por publication_id. Não invente estado.\n\n"
        f"CONTEXTO_CANONICO={json.dumps(context, ensure_ascii=False, default=str)}\n\n"
        f"MENSAGEM_USUARIO={text}"
    )

    try:
        evidence = execute_harness_ai_generation(
            prompt=prompt,
            authorization=authorization,
            routing_decision=routing,
        )
    finally:
        consume_harness_authorization(authorization)

    result = evidence.result if isinstance(evidence.result, dict) else {}
    answer = str(result.get("text") or "").strip()
    if not evidence.active or evidence.status != "EXECUTED" or not answer:
        raise RuntimeError("Harness-governed AI reasoning did not produce a usable answer")

    return {
        "answer": answer,
        "authority": evidence.authority,
        "authorized_action": evidence.authorized_action,
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "execution_id": evidence.execution_id,
        "capability_id": routing.selected_capability_id,
        "provider": evidence.provider,
        "model": result.get("model") or routing.selected_model,
        "fallback_occurred": routing.fallback_occurred,
        "zero_cost_operation": bool(routing.policy_metadata.get("zero_cost_operation")),
    }


def execute_telegram_asset_registration_capability(
    *,
    payload: dict[str, Any],
    authorization,
    routing_decision,
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{TELEGRAM_ASSET_CAPABILITY_ID}",
    )
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("Telegram asset routing action mismatch")
    if routing_decision.selected_capability_id != TELEGRAM_ASSET_CAPABILITY_ID:
        raise PermissionError("Telegram asset capability mismatch")
    if routing_decision.selected_executor_binding != TELEGRAM_ASSET_EXECUTOR_BINDING:
        raise PermissionError("Telegram asset executor escaped Registry binding")
    if not bool(payload.get("remote_verified")):
        raise ValueError("Telegram asset must be verified with getFile before persistence")

    asset_type = str(payload.get("asset_type") or "").strip().lower()
    media_kind = str(payload.get("media_kind") or "").strip().lower()
    mime_type = str(payload.get("mime_type") or "").strip().lower() or None
    if asset_type == "intro":
        if media_kind not in {"video", "document", "animation"}:
            raise ValueError("Intro must be a Telegram video/document/animation")
        if media_kind == "document" and mime_type and not mime_type.startswith("video/"):
            raise ValueError("Intro document must have a video MIME type")
    elif asset_type == "watermark":
        if media_kind not in {"photo", "document"}:
            raise ValueError("Watermark must be a Telegram photo/image document")
        if media_kind == "document" and mime_type and not mime_type.startswith("image/"):
            raise ValueError("Watermark document must have an image MIME type")
    else:
        raise ValueError("asset_type must be intro or watermark")

    record = upsert_active_brand_asset(
        asset_type=asset_type,
        telegram_file_id=str(payload["telegram_file_id"]),
        telegram_file_unique_id=str(payload["telegram_file_unique_id"]),
        media_kind=media_kind,
        file_name=payload.get("file_name"),
        mime_type=mime_type,
        file_size=payload.get("file_size"),
        width=payload.get("width"),
        height=payload.get("height"),
        duration_seconds=payload.get("duration_seconds"),
        telegram_user_id=int(payload["telegram_user_id"]),
        telegram_chat_id=int(payload["telegram_chat_id"]),
        telegram_message_id=int(payload["telegram_message_id"]),
        telegram_update_id=(
            int(payload["telegram_update_id"])
            if payload.get("telegram_update_id") is not None
            else None
        ),
        caption=str(payload.get("caption") or ""),
        remote_verified=True,
        provenance={
            "source": "telegram",
            "ingress": "telegram_harness_gateway",
            "routing_id": routing_decision.routing_id,
            "authorization_id": auth.authorization_id,
            "harness_decision_id": auth.harness_decision_id,
            "execution_id": auth.execution_id,
            "telegram_update_id": payload.get("telegram_update_id"),
            "telegram_message_id": payload.get("telegram_message_id"),
        },
    )
    consume_harness_authorization(auth)
    return {
        "status": "REGISTERED",
        "authority": auth.issued_by,
        "capability_id": TELEGRAM_ASSET_CAPABILITY_ID,
        "routing_id": routing_decision.routing_id,
        "authorization_id": auth.authorization_id,
        "asset": _safe_asset(record),
    }


def register_telegram_brand_asset_under_harness(payload: dict[str, Any]) -> dict[str, Any]:
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="register verified Telegram branding asset intro watermark provenance",
            authorized_action="EXECUTION",
            domain="telegram-ingress",
            required_capability_id=TELEGRAM_ASSET_CAPABILITY_ID,
            required_policy_tags=("telegram", "asset", "branding"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{TELEGRAM_ASSET_CAPABILITY_ID}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "ingress": "telegram",
            "telegram_user_id": payload.get("telegram_user_id"),
            "telegram_chat_id": payload.get("telegram_chat_id"),
            "telegram_message_id": payload.get("telegram_message_id"),
            "asset_type": payload.get("asset_type"),
        },
    )
    return execute_telegram_asset_registration_capability(
        payload=payload,
        authorization=authorization,
        routing_decision=routing,
    )
