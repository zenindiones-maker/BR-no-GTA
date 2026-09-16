from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable

from app.database.telegram_brand_asset_repository import (
    list_active_brand_assets,
    upsert_active_brand_asset,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
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
from app.services.telegram_fresh_research_service import (
    FreshResearchError,
    requires_fresh_research,
    research_fresh_gta6_under_harness,
)


TELEGRAM_ASSET_CAPABILITY_ID = "telegram.asset.register"
TELEGRAM_ASSET_EXECUTOR_BINDING = (
    "app.services.telegram_harness_service.execute_telegram_asset_registration_capability"
)


ProgressCallback = Callable[[str, str], None]


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


def _capability_context() -> list[dict[str, Any]]:
    prefixes = (
        "gta6.",
        "script.",
        "telegram.",
        "production.brand-assets",
        "ai.reasoning.text",
        "youtube.analytics",
        "knowledge.learn.youtube-analytics",
    )
    rows: list[dict[str, Any]] = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if not any(record.capability_id.startswith(prefix) for prefix in prefixes):
            continue
        rows.append(
            {
                "capability_id": record.capability_id,
                "domain": record.domain,
                "maturity": record.maturity,
                "availability": record.availability,
                "quality_class": record.quality_class,
                "executor_binding": record.executor_binding,
                "policy_tags": list(record.policy_tags),
            }
        )
    return rows


def _compact_fresh_packet(packet: dict[str, Any]) -> dict[str, Any]:
    official: list[dict[str, Any]] = []
    for source in (packet.get("official_sources") or [])[:3]:
        if not isinstance(source, dict):
            continue
        official.append(
            {
                "source_name": source.get("source_name"),
                "url": source.get("url"),
                "authority": "official",
                "checked_at": source.get("checked_at"),
                "content_excerpt": str(source.get("content_excerpt") or "")[:6000],
            }
        )
    secondary: list[dict[str, Any]] = []
    for source in (packet.get("secondary_sources") or [])[:12]:
        if not isinstance(source, dict):
            continue
        secondary.append(
            {
                "source_name": source.get("source_name"),
                "title": source.get("title"),
                "summary": str(source.get("summary") or "")[:700],
                "url": source.get("url"),
                "published_at": source.get("published_at"),
                "authority": source.get("authority"),
            }
        )
    return {
        "status": packet.get("status"),
        "checked_at": packet.get("checked_at"),
        "official_source_count": packet.get("official_source_count"),
        "secondary_source_count": packet.get("secondary_source_count"),
        "official_sources": official,
        "secondary_sources": secondary,
        "source_errors": (packet.get("source_errors") or [])[:8],
        "policy": packet.get("policy") or {},
    }


def _chat_context(
    message: str,
    *,
    fresh_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observation = build_gta6_observation()
    knowledge = query_gta6_knowledge_context(query=message)
    compact_observation = {
        "domain": observation.get("domain"),
        "source_of_truth": observation.get("source_of_truth"),
        "monitor": observation.get("monitor"),
    }
    return {
        "current_utc": datetime.now(timezone.utc).isoformat(),
        "observation": compact_observation,
        "knowledge": knowledge_context_to_dict(knowledge) if knowledge is not None else None,
        "capabilities": _capability_context(),
        "fresh_research": _compact_fresh_packet(fresh_packet) if fresh_packet is not None else None,
    }


def _emit(progress_callback: ProgressCallback | None, stage: str, message: str) -> None:
    if progress_callback is not None:
        progress_callback(stage, message)


def chat_under_harness(
    message: str,
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        raise ValueError("Telegram chat message is empty")
    if len(text) > 8000:
        raise ValueError("Telegram chat message is too long")

    freshness_required = requires_fresh_research(text)
    fresh = None
    if freshness_required:
        _emit(
            progress_callback,
            "RESEARCH",
            "🔎 Pesquisa atual obrigatória: consultando fontes oficiais da Rockstar e fontes configuradas no cloud...",
        )
        try:
            fresh = research_fresh_gta6_under_harness(text)
        except FreshResearchError as exc:
            return {
                "answer": (
                    "Não consegui verificar fontes oficiais atuais com evidência suficiente agora. "
                    "Por segurança, não vou completar a resposta usando memória antiga do modelo. "
                    "Tente novamente quando a pesquisa cloud estiver disponível."
                ),
                "authority": HARNESS_ISSUER,
                "authorized_action": "RESEARCH",
                "routing_id": None,
                "authorization_id": None,
                "execution_id": None,
                "capability_id": "gta6.research.fresh-cloud",
                "provider": None,
                "model": None,
                "fallback_occurred": False,
                "zero_cost_operation": True,
                "fresh_research_required": True,
                "fresh_research_status": "FAIL_CLOSED",
                "fresh_research_error": type(exc).__name__,
            }
        _emit(
            progress_callback,
            "VALIDATION",
            f"✅ Evidência fresca coletada em {fresh.checked_at}. Validando hierarquia de fontes antes do raciocínio...",
        )

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="answer one Telegram user message with governed grounded GTA6 reasoning",
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
            "fresh_research_required": freshness_required,
            "fresh_research_execution_id": fresh.execution_id if fresh is not None else None,
            "fresh_research_routing_id": fresh.routing_id if fresh is not None else None,
        },
    )

    context = _chat_context(
        text,
        fresh_packet=fresh.packet if fresh is not None else None,
    )
    prompt = (
        "Você é a interface conversacional do BR-no-GTA subordinada ao DeepSeek Harness. "
        "Responda em português do Brasil, de forma profissional, clara e prática. "
        "Você NÃO é uma autoridade paralela e NÃO deve afirmar que executou, publicou, apagou ou alterou algo apenas por conversa. "
        "Ações com efeito colateral dependem das capabilities e gates oficiais do Harness; publicação pública preserva o gate exato por publication_id. "
        "Não invente estado, fonte, capability ou fato.\n\n"
        "POLITICA_DE_VERDADE_E_FRESHNESS:\n"
        "1) Para fatos atuais de GTA VI, EVIDENCIA_FRESCA oficial da Rockstar prevalece sobre memória persistida e sobre conhecimento prévio do modelo.\n"
        "2) Fontes secundárias podem contextualizar, mas alegações importantes exigem corroboração; Reddit/comunidade é sinal, nunca confirmação.\n"
        "3) Ideias, temas, notícias e notas enviadas pelo usuário são entradas editoriais com proveniência, não fatos oficiais por si só.\n"
        "4) Se a pergunta exigir atualidade e EVIDENCIA_FRESCA não contiver confirmação, diga explicitamente que não encontrou confirmação atual; NÃO preencha a lacuna com memória do modelo.\n"
        "5) Se EVIDENCIA_FRESCA estiver presente e PASS, não diga que você não tem acesso atual às fontes; informe o horário checked_at quando relevante e use URLs reais do pacote.\n"
        "6) Se houver conflito entre memória antiga e fonte oficial fresca, trate a memória antiga como obsoleta e explique a atualização.\n"
        "7) Para perguntas sobre o próprio sistema, use apenas CAPABILITIES presentes no contexto; não prometa funções ausentes ou não comprovadas.\n"
        "8) Diferencie claramente FATO OFICIAL, REPORTAGEM/SECUNDÁRIA, RUMOR/SINAL DA COMUNIDADE e IDEIA DO USUÁRIO.\n\n"
        f"CONTEXTO_CANONICO={json.dumps(context, ensure_ascii=False, default=str)}\n\n"
        f"MENSAGEM_USUARIO={text}"
    )

    _emit(
        progress_callback,
        "REASONING",
        "🧠 Evidências prontas. Roteando raciocínio governado pelo Harness no cloud...",
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
        "fresh_research_required": freshness_required,
        "fresh_research_status": "PASS" if fresh is not None else "NOT_REQUIRED",
        "fresh_research_checked_at": fresh.checked_at if fresh is not None else None,
        "fresh_research_routing_id": fresh.routing_id if fresh is not None else None,
        "fresh_research_execution_ref": fresh.execution_ref if fresh is not None else None,
        "official_source_count": fresh.official_source_count if fresh is not None else 0,
        "secondary_source_count": fresh.secondary_source_count if fresh is not None else 0,
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
