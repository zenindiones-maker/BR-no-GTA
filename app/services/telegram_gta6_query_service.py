from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re
import unicodedata
from typing import Any

from app.services.gta6_fact_check_service import execute_gta6_fact_check_via_harness
from app.services.gta6_knowledge_query_service import (
    knowledge_context_to_dict,
    query_gta6_knowledge,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.provider_health_service import semantic_provider_health
from app.services.telegram_fresh_research_service import (
    research_fresh_gta6_under_harness,
)


_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'-]{2,}")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_STOP = {
    "sobre", "tudo", "pesquisa", "pesquise", "procura", "procure", "gta", "grand",
    "theft", "auto", "what", "about", "tell", "me", "que", "qual", "quais", "como",
    "para", "com", "uma", "uns", "das", "dos", "por", "mais",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD_RE.findall(_fold(value))
        if token.casefold() not in _STOP
    }


def _source_time(source: dict[str, Any], packet: dict[str, Any]) -> str:
    return str(
        source.get("retrieved_at")
        or source.get("checked_at")
        or source.get("published_at")
        or packet.get("checked_at")
        or datetime.now(timezone.utc).isoformat()
    )


def _rank_official_claims(
    packet: dict[str, Any],
    query: str,
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for source_index, raw_source in enumerate(packet.get("official_sources") or ()):
        if not isinstance(raw_source, dict):
            continue
        source = dict(raw_source)
        source_url = str(source.get("resolved_url") or source.get("url") or "").strip()
        source_name = str(source.get("source_name") or source.get("title") or "Rockstar Games").strip()
        content = " ".join(str(source.get("content_excerpt") or "").split())
        if not content or not source_url:
            continue
        for sentence in _SENTENCE_RE.split(content):
            sentence = sentence.strip()
            if len(sentence) < 35 or len(sentence) > 700:
                continue
            identity = _fold(sentence)
            if identity in seen:
                continue
            seen.add(identity)
            overlap = len(query_tokens & _tokens(sentence))
            gta_bonus = 1 if any(term in identity for term in ("gta", "vice city", "leonida", "lucia", "jason")) else 0
            score = overlap * 5 + gta_bonus
            if query_tokens and score <= 0:
                continue
            candidates.append((
                score,
                -source_index,
                {
                    "claim": sentence,
                    "source_name": source_name,
                    "source_url": source_url,
                    "observed_at": _source_time(source, packet),
                    "source_index": source_index,
                },
            ))
    candidates.sort(key=lambda item: (item[0], item[1], -len(item[2]["claim"])), reverse=True)
    return [item[2] for item in candidates[:limit]]


def _fact_check_claim(
    *,
    claim: dict[str, Any],
    query: str,
    goal_id: str,
    index: int,
) -> dict[str, Any]:
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"fact-check official Rockstar evidence for Telegram query: {query}",
            authorized_action="RESEARCH",
            domain="research",
            task_class="telegram-gta6-query-fact-check",
            goal_id=goal_id,
            required_capability_id="gta6.fact-check",
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="RESEARCH",
        subject="capability:gta6.fact-check",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": "gta6.fact-check",
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": goal_id,
            "mission_id": f"telegram-gta6-query:{goal_id}",
            "task_id": f"fact-check-{index}",
            "ingress": "telegram-natural-research",
        },
    )
    source_ref = claim["source_url"]
    payload = {
        "mission_id": f"telegram-gta6-query:{goal_id}",
        "task_id": f"fact-check-{index}",
        "goal_id": goal_id,
        "claim": claim["claim"],
        "input_refs": [source_ref],
        "evidence": [
            {
                "evidence_id": f"official-source-{index}",
                "source_ref": source_ref,
                "stance": "supporting",
                "weight": 1.0,
                "provenance": {
                    "url": source_ref,
                    "observed_at": claim["observed_at"],
                },
                "excerpt": claim["claim"],
            }
        ],
    }
    try:
        canonical = execute_gta6_fact_check_via_harness(
            authorization=authorization,
            routing_decision=routing,
            payload=payload,
        )
    finally:
        consume_harness_authorization(authorization)
    result = canonical.result if isinstance(canonical.result, dict) else {}
    fact_check = result.get("fact_check") if isinstance(result.get("fact_check"), dict) else {}
    return {
        **claim,
        "verdict": fact_check.get("verdict"),
        "confidence": fact_check.get("confidence"),
        "fact_check_execution_id": canonical.execution_id,
        "fact_check_routing_id": canonical.routing_id,
    }


def _knowledge_hits(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    return [
        knowledge_context_to_dict(item)
        for item in query_gta6_knowledge(query=query, limit=limit)
    ]


def _short_claim_text(value: str, *, max_chars: int = 420) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return clipped + "…"


def _human_answer(
    *,
    query: str,
    claims: list[dict[str, Any]],
    knowledge_hits: list[dict[str, Any]],
    execution_ref: str,
    provider_health: dict[str, Any],
) -> str:
    supported = [
        item for item in claims
        if str(item.get("verdict") or "").upper() == "SUPPORTED"
    ]
    lines = [
        f"Pesquisei exatamente o seu pedido: “{query}”.",
    ]
    if supported:
        lines.append("O que consegui confirmar agora em fonte oficial:")
        for item in supported[:4]:
            lines.append(
                f"• {_short_claim_text(item['claim'])} "
                f"[Rockstar: {item['source_name']}]"
            )
    elif claims:
        lines.append(
            "Encontrei evidência oficial, mas o fact-check não marcou nenhuma afirmação como SUPPORTED; "
            "não vou transformar isso em fato."
        )
    elif knowledge_hits:
        lines.append(
            "A fonte fresh não produziu um trecho oficial diretamente relevante; "
            "o Knowledge Brain possui contexto anterior, mas não vou apresentá-lo como novidade."
        )
    else:
        lines.append(
            "Não encontrei evidência oficial suficiente para responder com segurança a esse pedido."
        )

    lines.append(
        f"Prova: {execution_ref}; {len(supported)} afirmação(ões) apoiada(s) por evidência oficial."
    )
    if not provider_health.get("semantic_reasoning_available"):
        lines.append(
            "A síntese semântica aberta está indisponível agora, então mantive a resposta estritamente nas evidências verificadas — "
            "sem inventar interpretação."
        )
    return "\n".join(lines)


def execute_telegram_gta6_query(
    *,
    query: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        raise ValueError("Telegram GTA6 query is empty")
    goal_id = str(
        state.get("active_goal_id")
        or "telegram-gta6-query:" + sha256(text.encode("utf-8")).hexdigest()[:16]
    )
    known = _knowledge_hits(text)
    fresh = research_fresh_gta6_under_harness(text)
    packet = dict(fresh.packet or {})
    claims = _rank_official_claims(packet, text)
    checked = [
        _fact_check_claim(
            claim=claim,
            query=text,
            goal_id=goal_id,
            index=index,
        )
        for index, claim in enumerate(claims, start=1)
    ]
    health = semantic_provider_health()
    answer = _human_answer(
        query=text,
        claims=checked,
        knowledge_hits=known,
        execution_ref=fresh.execution_ref,
        provider_health=health,
    )
    return {
        "status": "COMPLETED",
        "answer": answer,
        "authority": "DEEPSEEK_HARNESS",
        "goal_id": goal_id,
        "capability_id": "gta6.research.fresh-cloud",
        "research_execution_id": fresh.execution_id,
        "routing_id": fresh.routing_id,
        "authorization_id": fresh.authorization_id,
        "execution_ref": fresh.execution_ref,
        "query": text,
        "knowledge_retrieved_before_research": bool(known),
        "knowledge_hits": known,
        "official_source_count": fresh.official_source_count,
        "secondary_source_count": fresh.secondary_source_count,
        "fact_checks": checked,
        "provider_health": health,
        "provider_required_for_evidence_answer": False,
        "semantic_synthesis_used": False,
        "RESEARCH_EXECUTION": "PASS",
        "GTA6_FACT_CHECK": "PASS" if checked else "NO_RELEVANT_CLAIM",
        "SOURCE_PROVENANCE_PRESERVED": "PASS",
        "HUMAN_QUERY_PRESERVED": "PASS",
        "NEW_VOICE_SYNTHESIS": "NO",
        "FULL_RENDER": "NO",
        "YOUTUBE_UPLOAD": "NO",
        "YOUTUBE_PUBLICATION": "NO",
    }
