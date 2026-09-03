from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.database.memory_claim_evidence_repository import (
    list_memory_claim_evidence_for_claim,
)
from app.database.memory_claim_repository import (
    get_memory_claim,
)
from app.database.memory_event_repository import (
    get_memory_event,
)
from app.database.memory_record_claims_repository import (
    list_claims_for_memory_record,
)
from app.database.memory_repository import (
    list_memories,
)


class MemoryRetrievalError(ValueError):
    """Erro de domínio da recuperação de memória."""


@dataclass(frozen=True)
class MemoryEvidenceLineage:
    """Evidência histórica associada a um Claim."""

    relation_id: int
    event_id: int
    evidence_role: str
    weight: float
    event_type: str
    source_type: str
    source_id: str | None
    content: str
    scope: str
    occurred_at: str | None
    observed_at: str | None
    provenance: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MemoryClaimLineage:
    """Claim e todas as evidências conhecidas."""

    claim_id: int
    claim: str
    claim_type: str
    confidence: float
    status: str
    scope: str
    valid_at: str | None
    invalid_at: str | None
    extraction_method: str
    evidences: tuple[MemoryEvidenceLineage, ...]


@dataclass(frozen=True)
class MemoryRetrievalResult:
    """Resultado de Retrieval com proveniência completa."""

    memory_id: int
    content: str
    memory_type: str
    source_type: str
    source_id: str | None
    confidence: float
    importance: float
    scope: str
    status: str
    valid_at: str | None
    invalid_at: str | None
    access_count: int
    lexical_score: float
    ranking_score: float
    claims: tuple[MemoryClaimLineage, ...]


def _normalize_text(value: str) -> str:
    return " ".join(
        re.findall(
            r"\w+",
            value.lower(),
            flags=re.UNICODE,
        )
    )


def _tokenize(value: str) -> set[str]:
    normalized = _normalize_text(value)

    if not normalized:
        return set()

    return set(normalized.split())


def _calculate_lexical_score(
    query_tokens: set[str],
    content: str,
) -> float:
    if not query_tokens:
        return 0.0

    content_tokens = _tokenize(content)

    if not content_tokens:
        return 0.0

    matched_tokens = query_tokens & content_tokens

    return round(
        len(matched_tokens) / len(query_tokens),
        4,
    )


def _calculate_ranking_score(
    *,
    lexical_score: float,
    confidence: float,
    importance: float,
) -> float:
    confidence_score = max(
        0.0,
        min(1.0, confidence / 10.0),
    )

    importance_score = max(
        0.0,
        min(1.0, importance / 10.0),
    )

    score = (
        lexical_score * 0.60
        + confidence_score * 0.25
        + importance_score * 0.15
    )

    return round(score, 4)


def _build_evidence_lineage(
    *,
    relation: dict[str, Any],
) -> MemoryEvidenceLineage | None:
    event = get_memory_event(
        int(relation["event_id"])
    )

    if event is None:
        return None

    return MemoryEvidenceLineage(
        relation_id=int(relation["id"]),
        event_id=int(event["id"]),
        evidence_role=relation["evidence_role"],
        weight=float(relation["weight"]),
        event_type=event["event_type"],
        source_type=event["source_type"],
        source_id=event["source_id"],
        content=event["content"],
        scope=event["scope"],
        occurred_at=event["occurred_at"],
        observed_at=event["observed_at"],
        provenance=event["provenance"],
        metadata=event["metadata"],
    )


def _build_claim_lineage(
    *,
    claim_id: int,
) -> MemoryClaimLineage | None:
    claim = get_memory_claim(claim_id)

    if claim is None:
        return None

    evidence_relations = (
        list_memory_claim_evidence_for_claim(
            claim_id
        )
    )

    evidences: list[MemoryEvidenceLineage] = []

    for relation in evidence_relations:
        evidence = _build_evidence_lineage(
            relation=relation,
        )

        if evidence is not None:
            evidences.append(evidence)

    return MemoryClaimLineage(
        claim_id=int(claim["id"]),
        claim=claim["claim"],
        claim_type=claim["claim_type"],
        confidence=float(claim["confidence"]),
        status=claim["status"],
        scope=claim["scope"],
        valid_at=claim["valid_at"],
        invalid_at=claim["invalid_at"],
        extraction_method=claim["extraction_method"],
        evidences=tuple(evidences),
    )


def _build_memory_claim_lineage(
    memory_id: int,
) -> tuple[MemoryClaimLineage, ...]:
    relations = list_claims_for_memory_record(
        memory_id
    )

    claims: list[MemoryClaimLineage] = []

    for relation in relations:
        claim = _build_claim_lineage(
            claim_id=int(relation["claim_id"])
        )

        if claim is not None:
            claims.append(claim)

    return tuple(claims)


def retrieve_semantic_memory(
    *,
    query: str,
    scope: str = "gta6",
    limit: int = 10,
) -> list[MemoryRetrievalResult]:
    """
    Recupera memórias semânticas ativas por relevância lexical.

    Cada resultado inclui a linhagem:

        Memory
        → Claim
        → Evidence
        → Event
    """

    if (
        not isinstance(query, str)
        or not query.strip()
    ):
        raise MemoryRetrievalError(
            "query deve ser uma string não vazia."
        )

    if (
        not isinstance(scope, str)
        or not scope.strip()
    ):
        raise MemoryRetrievalError(
            "scope deve ser uma string não vazia."
        )

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise MemoryRetrievalError(
            "limit deve ser um inteiro positivo."
        )

    query_tokens = _tokenize(query)

    memories = list_memories(
        memory_type="semantic",
        scope=scope,
        status="active",
    )

    results: list[MemoryRetrievalResult] = []

    for memory in memories:
        lexical_score = _calculate_lexical_score(
            query_tokens,
            memory["content"],
        )

        if lexical_score <= 0:
            continue

        ranking_score = _calculate_ranking_score(
            lexical_score=lexical_score,
            confidence=float(memory["confidence"]),
            importance=float(memory["importance"]),
        )

        claims = _build_memory_claim_lineage(
            int(memory["id"])
        )

        results.append(
            MemoryRetrievalResult(
                memory_id=int(memory["id"]),
                content=memory["content"],
                memory_type=memory["memory_type"],
                source_type=memory["source_type"],
                source_id=memory["source_id"],
                confidence=float(memory["confidence"]),
                importance=float(memory["importance"]),
                scope=memory["scope"],
                status=memory["status"],
                valid_at=memory["valid_at"],
                invalid_at=memory["invalid_at"],
                access_count=int(memory["access_count"]),
                lexical_score=lexical_score,
                ranking_score=ranking_score,
                claims=claims,
            )
        )

    results.sort(
        key=lambda result: (
            -result.ranking_score,
            -result.lexical_score,
            -result.confidence,
            -result.importance,
            result.memory_id,
        )
    )

    return results[:limit]


def retrieval_result_to_dict(
    result: MemoryRetrievalResult,
) -> dict[str, Any]:
    """Serializa um resultado de Retrieval com linhagem completa."""

    return {
        "memory_id": result.memory_id,
        "content": result.content,
        "memory_type": result.memory_type,
        "source_type": result.source_type,
        "source_id": result.source_id,
        "confidence": result.confidence,
        "importance": result.importance,
        "scope": result.scope,
        "status": result.status,
        "valid_at": result.valid_at,
        "invalid_at": result.invalid_at,
        "access_count": result.access_count,
        "lexical_score": result.lexical_score,
        "ranking_score": result.ranking_score,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "claim": claim.claim,
                "claim_type": claim.claim_type,
                "confidence": claim.confidence,
                "status": claim.status,
                "scope": claim.scope,
                "valid_at": claim.valid_at,
                "invalid_at": claim.invalid_at,
                "extraction_method": claim.extraction_method,
                "evidences": [
                    {
                        "relation_id": evidence.relation_id,
                        "event_id": evidence.event_id,
                        "evidence_role": evidence.evidence_role,
                        "weight": evidence.weight,
                        "event_type": evidence.event_type,
                        "source_type": evidence.source_type,
                        "source_id": evidence.source_id,
                        "content": evidence.content,
                        "scope": evidence.scope,
                        "occurred_at": evidence.occurred_at,
                        "observed_at": evidence.observed_at,
                        "provenance": evidence.provenance,
                        "metadata": evidence.metadata,
                    }
                    for evidence in claim.evidences
                ],
            }
            for claim in result.claims
        ],
    }
