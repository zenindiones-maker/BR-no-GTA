from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.database import continuous_operation_repository as continuous_repository
from app.database.memory_claim_repository import get_memory_claim, list_memory_claims
from app.services.gta6_knowledge_query_service import (
    knowledge_context_to_dict,
    query_gta6_knowledge,
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


def _semantic_hits(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    return [
        knowledge_context_to_dict(item)
        for item in query_gta6_knowledge(query=query, limit=limit)
    ]


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


def _human_answer(query: str, claims: list[dict[str, Any]]) -> str:
    if not claims:
        return (
            "Não encontrei conhecimento canônico suficiente para esse pedido no estado atual. "
            "Isso não é falha de provider: apenas significa que o Knowledge Brain/Memory Plane "
            "ainda não possui um claim ativo correspondente."
        )

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


def recall_canonical_gta6_knowledge(
    query: str,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        raise ValueError("knowledge recall query is empty")
    if _explicitly_outside_gta6_scope(text):
        return {
            "status": "NO_CANONICAL_KNOWLEDGE_MATCH",
            "answer": (
                "Não há conhecimento canônico suficiente desse assunto no escopo GTA 6. "
                "Não vou preencher a lacuna com outro jogo nem chamar provider semântico só para fabricar resposta."
            ),
            "query": text,
            "claims": [],
            "semantic_memory_hits": [],
            "provider_independent": True,
            "provider_calls": 0,
            "semantic_provider_required": False,
            "canonical_memory_plane": "BR_SQLITE",
            "knowledge_authority": "KNOWLEDGE_BRAIN",
            "obsidian_role": "PUBLISHED_MEMORY_VIEW",
            "SOURCE_PROVENANCE_PRESERVED": "NO_MATCH",
        }

    semantic_hits = _semantic_hits(text, limit=min(limit, 5))
    claims = _lineage_claims(text, limit=limit)

    if not claims and _is_broad_gta6_query(text):
        claims = _fallback_active_claims(limit=limit)

    if not claims and semantic_hits:
        flattened: list[dict[str, Any]] = []
        for memory in semantic_hits:
            for claim in memory.get("claims") or ():
                flattened.append({
                    "claim_id": claim.get("claim_id"),
                    "subject": None,
                    "claim": claim.get("content"),
                    "claim_type": claim.get("claim_type"),
                    "confidence": claim.get("confidence"),
                    "status": claim.get("status"),
                    "source_id": (
                        (claim.get("evidences") or [{}])[0].get("source_id")
                        if claim.get("evidences") else None
                    ),
                    "source_url": None,
                    "source_type": (
                        (claim.get("evidences") or [{}])[0].get("source_type")
                        if claim.get("evidences") else None
                    ),
                    "published_at": None,
                    "observed_at": None,
                    "evidence_ref": (
                        (claim.get("evidences") or [{}])[0].get("provenance")
                        if claim.get("evidences") else None
                    ),
                    "evidence_class": None,
                    "supersedes_claim_id": None,
                    "related_claims": [],
                })
        claims = flattened[:limit]

    return {
        "status": "CANONICAL_KNOWLEDGE_RECALLED" if claims else "NO_CANONICAL_KNOWLEDGE_MATCH",
        "answer": _human_answer(text, claims),
        "query": text,
        "claims": claims,
        "semantic_memory_hits": semantic_hits,
        "provider_independent": True,
        "provider_calls": 0,
        "semantic_provider_required": False,
        "canonical_memory_plane": "BR_SQLITE",
        "knowledge_authority": "KNOWLEDGE_BRAIN",
        "obsidian_role": "PUBLISHED_MEMORY_VIEW",
        "SOURCE_PROVENANCE_PRESERVED": (
            "PASS"
            if any(item.get("source_url") or item.get("evidence_ref") for item in claims)
            else "NO_MATCH"
        ),
    }
