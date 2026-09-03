from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.memory_retrieval_service import (
    MemoryClaimLineage,
    MemoryEvidenceLineage,
    MemoryRetrievalResult,
    retrieve_semantic_memory,
)


class GTA6KnowledgeQueryError(ValueError):
    """Erro de domínio das consultas ao Knowledge Core GTA6."""


@dataclass(frozen=True)
class GTA6KnowledgeEvidence:
    """Evidência de conhecimento exposta pelo Knowledge Core."""

    relation_id: int
    event_id: int
    role: str
    weight: float
    event_type: str
    source_type: str
    source_id: str | None
    content: str
    provenance: str


@dataclass(frozen=True)
class GTA6KnowledgeClaim:
    """Claim de conhecimento exposto pelo Knowledge Core."""

    claim_id: int
    content: str
    claim_type: str
    confidence: float
    status: str
    extraction_method: str
    evidences: tuple[GTA6KnowledgeEvidence, ...]


@dataclass(frozen=True)
class GTA6KnowledgeContext:
    """
    Unidade de conhecimento consumível por Radar,
    Evaluation e Editorial.

    A estrutura oculta detalhes dos repositórios internos
    e preserva a linhagem completa do conhecimento.
    """

    memory_id: int
    content: str
    confidence: float
    importance: float
    scope: str
    ranking_score: float
    claims: tuple[GTA6KnowledgeClaim, ...]


def _build_evidence(
    evidence: MemoryEvidenceLineage,
) -> GTA6KnowledgeEvidence:
    return GTA6KnowledgeEvidence(
        relation_id=evidence.relation_id,
        event_id=evidence.event_id,
        role=evidence.evidence_role,
        weight=evidence.weight,
        event_type=evidence.event_type,
        source_type=evidence.source_type,
        source_id=evidence.source_id,
        content=evidence.content,
        provenance=evidence.provenance,
    )


def _build_claim(
    claim: MemoryClaimLineage,
) -> GTA6KnowledgeClaim:
    evidences = tuple(
        _build_evidence(evidence)
        for evidence in claim.evidences
    )

    return GTA6KnowledgeClaim(
        claim_id=claim.claim_id,
        content=claim.claim,
        claim_type=claim.claim_type,
        confidence=claim.confidence,
        status=claim.status,
        extraction_method=claim.extraction_method,
        evidences=evidences,
    )


def _build_context(
    result: MemoryRetrievalResult,
) -> GTA6KnowledgeContext:
    claims = tuple(
        _build_claim(claim)
        for claim in result.claims
    )

    return GTA6KnowledgeContext(
        memory_id=result.memory_id,
        content=result.content,
        confidence=result.confidence,
        importance=result.importance,
        scope=result.scope,
        ranking_score=result.ranking_score,
        claims=claims,
    )


def query_gta6_knowledge(
    *,
    query: str,
    limit: int = 10,
) -> list[GTA6KnowledgeContext]:
    """
    Consulta o Knowledge Core GTA6.

    Esta função é a interface pública para consumidores
    como Radar, Evaluation e Editorial.

    A implementação delega integralmente ao Retrieval
    semântico já existente e validado.
    """

    if (
        not isinstance(query, str)
        or not query.strip()
    ):
        raise GTA6KnowledgeQueryError(
            "query deve ser uma string não vazia."
        )

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise GTA6KnowledgeQueryError(
            "limit deve ser um inteiro positivo."
        )

    results = retrieve_semantic_memory(
        query=query,
        scope="gta6",
        limit=limit,
    )

    return [
        _build_context(result)
        for result in results
    ]


def query_gta6_knowledge_context(
    *,
    query: str,
) -> GTA6KnowledgeContext | None:
    """
    Retorna o contexto de conhecimento mais relevante.

    Retorna None quando nenhuma memória relevante é encontrada.
    """

    results = query_gta6_knowledge(
        query=query,
        limit=1,
    )

    if not results:
        return None

    return results[0]


def knowledge_context_to_dict(
    context: GTA6KnowledgeContext,
) -> dict[str, Any]:
    """Serializa um contexto do Knowledge Core."""

    return {
        "memory_id": context.memory_id,
        "content": context.content,
        "confidence": context.confidence,
        "importance": context.importance,
        "scope": context.scope,
        "ranking_score": context.ranking_score,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "content": claim.content,
                "claim_type": claim.claim_type,
                "confidence": claim.confidence,
                "status": claim.status,
                "extraction_method": claim.extraction_method,
                "evidences": [
                    {
                        "relation_id": evidence.relation_id,
                        "event_id": evidence.event_id,
                        "role": evidence.role,
                        "weight": evidence.weight,
                        "event_type": evidence.event_type,
                        "source_type": evidence.source_type,
                        "source_id": evidence.source_id,
                        "content": evidence.content,
                        "provenance": evidence.provenance,
                    }
                    for evidence in claim.evidences
                ],
            }
            for claim in context.claims
        ],
    }
