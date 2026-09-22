from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.database import continuous_operation_repository as continuous_repository
from app.database.memory_claim_repository import get_memory_claim, list_memory_claims
from app.services.gta6_knowledge_retrieval_service import (
    KNOWLEDGE_RETRIEVE_CAPABILITY_ID,
    execute_gta6_knowledge_retrieval_capability,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


_STOP = {
    "conhecimento", "memoria", "sobre", "do", "da", "de", "o", "a", "os", "as",
    "que", "sabemos", "sabe", "voce", "gta", "6", "gta6", "gta-6",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{1,}", _fold(value))
        if token not in _STOP
    }


def _is_broad_gta6_query(
    query: str,
    *,
    project_context: str = "",
    subject_context: str = "",
) -> bool:
    text = _fold(query)
    mentions_gta6 = any(term in text for term in (
        "gta 6", "gta6", "gta vi", "grand theft auto vi",
    ))
    context = _fold(f"{project_context} {subject_context}")
    project_is_gta6 = any(term in context for term in (
        "br-no-gta", "gta 6", "gta6", "gta vi",
    ))
    return (mentions_gta6 or project_is_gta6) and not _tokens(query)


def _explicitly_outside_gta6_scope(query: str) -> bool:
    text = _fold(query)
    if any(term in text for term in ("gta 6", "gta6", "gta vi", "grand theft auto vi")):
        return False
    return bool(re.search(r"\bgta\s*(?:7|vii)\b", text))


def _lineage_claims(
    query: str,
    *,
    limit: int = 8,
    project_context: str = "",
    subject_context: str = "",
) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    broad = _is_broad_gta6_query(
        query,
        project_context=project_context,
        subject_context=subject_context,
    )
    if not broad and not query_tokens:
        return []
    rows = continuous_repository.list_claim_lineage(limit=500)
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    seen: set[int] = set()

    for lineage in rows:
        claim_id = int(lineage["claim_id"])
        if claim_id in seen:
            continue
        claim = get_memory_claim(claim_id)
        if claim is None or claim.get("scope") != "gta6":
            continue
        if str(claim.get("status") or "").casefold() != "active":
            continue

        subject = str(lineage.get("subject") or "")
        claim_text = str(claim.get("claim") or "")
        haystack = _fold(" ".join((
            subject,
            claim_text,
            str(lineage.get("source_id") or ""),
            str(lineage.get("source_url") or ""),
        )))
        overlap = sum(1 for token in query_tokens if token in haystack)
        if not broad and query_tokens and overlap <= 0:
            continue

        evidence_class = str(lineage.get("evidence_class") or "").upper()
        source_type = str(lineage.get("source_type") or "").upper()
        trust_bonus = 4 if evidence_class in {"OFFICIAL", "PRIMARY_SOURCE"} else 0
        trust_bonus += 2 if source_type in {"OFFICIAL", "PRIMARY_SOURCE"} else 0
        score = overlap * 10 + trust_bonus

        ranked.append((
            score,
            str(lineage.get("observed_at") or ""),
            {
                "claim_id": claim_id,
                "subject": subject,
                "claim": claim_text,
                "claim_type": claim.get("claim_type"),
                "confidence": claim.get("confidence"),
                "status": claim.get("status"),
                "source_id": lineage.get("source_id"),
                "source_url": lineage.get("source_url"),
                "source_type": lineage.get("source_type"),
                "published_at": lineage.get("published_at"),
                "observed_at": lineage.get("observed_at"),
                "evidence_ref": lineage.get("evidence_ref"),
                "evidence_class": lineage.get("evidence_class"),
                "supersedes_claim_id": lineage.get("supersedes_claim_id"),
                "related_claims": list(lineage.get("related_claims") or ()),
            },
        ))
        seen.add(claim_id)

    ranked.sort(key=lambda row: (row[0], row[1], row[2]["claim_id"]), reverse=True)
    return [row[2] for row in ranked[:limit]]


def _fallback_active_claims(*, limit: int = 8) -> list[dict[str, Any]]:
    rows = list_memory_claims(scope="gta6", status="active", limit=200)
    rows = list(reversed(rows))
    return [
        {
            "claim_id": int(item["id"]),
            "subject": None,
            "claim": item["claim"],
            "claim_type": item["claim_type"],
            "confidence": item["confidence"],
            "status": item["status"],
            "source_id": None,
            "source_url": None,
            "source_type": None,
            "published_at": None,
            "observed_at": item.get("updated_at"),
            "evidence_ref": None,
            "evidence_class": None,
            "supersedes_claim_id": None,
            "related_claims": [],
        }
        for item in rows[:limit]
    ]


def _human_answer(
    query: str,
    claims: list[dict[str, Any]],
    *,
    broad_context: bool,
) -> str:
    if not claims:
        return (
            "Não encontrei conhecimento canônico suficiente para esse pedido no estado atual. "
            "Isso não é falha de provider: apenas significa que o Knowledge Brain/Memory Plane "
            "ainda não possui um claim ativo correspondente."
        )

    primary_sources = {
        str(item.get("source_url") or item.get("source_id") or "").strip()
        for item in claims
        if str(item.get("source_type") or item.get("evidence_class") or "").upper()
        in {"OFFICIAL", "PRIMARY_SOURCE"}
        and str(item.get("source_url") or item.get("source_id") or "").strip()
    }
    if broad_context:
        lines = [
            "Tenho conhecimento canônico de GTA 6 já validado no estado atual.",
            (
                f"Esta resposta cobre {len(claims)} claim(s) relevante(s) e "
                f"{len(primary_sources)} fonte(s) primária(s)/oficial(is) associada(s)."
            ),
            "Alguns registros disponíveis:",
        ]
    else:
        lines = ["Conhecimento canônico disponível agora:"]
    for item in claims[:8]:
        subject = str(item.get("subject") or "").strip()
        prefix = f"{subject}: " if subject else ""
        source = str(item.get("source_url") or "").strip()
        evidence_class = str(item.get("evidence_class") or "").strip().upper()
        suffix_bits = []
        if evidence_class:
            suffix_bits.append(evidence_class)
        if source:
            suffix_bits.append(source)
        suffix = f" [{' | '.join(suffix_bits)}]" if suffix_bits else ""
        lines.append(f"• {prefix}{str(item.get('claim') or '').strip()}{suffix}")

    lines.append(
        "Fonte da resposta: memória canônica BR-no-GTA. "
        "Obsidian é a projeção humana desse mesmo estado, não um banco paralelo."
    )
    return "\n".join(lines)


def _harness_retrieve(query: str, *, limit: int) -> dict[str, Any]:
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="bounded canonical GTA6 knowledge recall for Telegram group",
            authorized_action="RESEARCH",
            domain="gta6-knowledge",
            task_class="telegram-gta6-knowledge-recall",
            goal_id="telegram-knowledge-recall",
            required_capability_id=KNOWLEDGE_RETRIEVE_CAPABILITY_ID,
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{KNOWLEDGE_RETRIEVE_CAPABILITY_ID}",
        harness_decision_id=routing.routing_id,
        execution_id=f"telegram-knowledge-recall:{routing.routing_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": KNOWLEDGE_RETRIEVE_CAPABILITY_ID,
            "surface": "telegram_group",
            "authority": "DEEPSEEK_HARNESS",
        },
    )
    try:
        result = execute_gta6_knowledge_retrieval_capability(
            authorization=authorization,
            routing_decision=routing,
            payload={
                "query": query,
                "limit": limit,
                "max_context_bytes": 24 * 1024,
                "include_history": False,
            },
        )
    finally:
        consume_harness_authorization(authorization)
    return {
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        **result,
    }


def recall_canonical_gta6_knowledge(
    query: str,
    *,
    limit: int = 8,
    project_context: str = "",
    subject_context: str = "",
) -> dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        raise ValueError("knowledge recall query is empty")
    if _explicitly_outside_gta6_scope(text):
        return {
            "status": "NO_CANONICAL_KNOWLEDGE_MATCH",
            "answer": (
                "Não há conhecimento canônico suficiente desse assunto no escopo GTA 6. "
                "Não vou preencher a lacuna com outro jogo nem fabricar resposta."
            ),
            "query": text,
            "claims": [],
            "provider_independent": True,
            "provider_calls": 0,
            "canonical_memory_plane": "BR_SQLITE",
            "knowledge_authority": "KNOWLEDGE_BRAIN",
            "human_surface": "telegram_group",
            "HARNESS_GOVERNED_RETRIEVAL": "PASS",
            "SOURCE_PROVENANCE_PRESERVED": "NO_MATCH",
        }

    broad_context = _is_broad_gta6_query(
        text,
        project_context=project_context,
        subject_context=subject_context,
    )
    retrieval_query = text
    if broad_context and not _tokens(text):
        retrieval_query = "GTA VI canonical verified knowledge"
    retrieved = _harness_retrieve(retrieval_query, limit=max(1, min(limit, 12)))
    result = dict(retrieved.get("result") or {})
    claims = list(result.get("knowledge_units") or ())
    if not claims and broad_context:
        claims = _fallback_active_claims(limit=limit)

    return {
        "status": (
            "CANONICAL_KNOWLEDGE_RECALLED"
            if claims else "NO_CANONICAL_KNOWLEDGE_MATCH"
        ),
        "answer": _human_answer(text, claims, broad_context=broad_context),
        "query": text,
        "claims": claims,
        "provider_independent": True,
        "provider_calls": 0,
        "semantic_provider_required": False,
        "context_resolved_scope": "gta6" if broad_context else None,
        "project_context": project_context or None,
        "subject_context": subject_context or None,
        "canonical_memory_plane": "BR_SQLITE",
        "knowledge_authority": "KNOWLEDGE_BRAIN",
        "obsidian_role": "LONG_TERM_HUMAN_KNOWLEDGE_VIEW",
        "human_surface": "telegram_group",
        "retrieval_mode": result.get("retrieval_mode"),
        "retrieval_context_bytes": result.get("context_bytes"),
        "retrieval_bounded": result.get("bounded_context"),
        "harness_routing_id": retrieved.get("routing_id"),
        "HARNESS_GOVERNED_RETRIEVAL": "PASS",
        "SOURCE_PROVENANCE_PRESERVED": (
            "PASS"
            if claims and all(
                item.get("source_url") or item.get("evidence_ref")
                for item in claims
            )
            else "NO_MATCH"
        ),
    }

