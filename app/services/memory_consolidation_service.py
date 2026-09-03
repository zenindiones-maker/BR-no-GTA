from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.memory_claim_service import (
    MemoryClaim,
)
from app.services.memory_service import (
    Memory,
)


class MemoryConsolidationError(ValueError):
    """Erro de domínio da consolidação de memória."""


VALID_CONSOLIDATION_STATUSES = {
    "active",
    "uncertain",
}


@dataclass(frozen=True)
class MemoryConsolidationResult:
    """Resultado determinístico da consolidação de um Claim."""

    claim_id: int
    memory: Memory
    supporting_evidence_count: int
    contradicting_evidence_count: int
    supporting_weight: float
    contradicting_weight: float
    evidence_balance: float


def _validate_evidence(
    evidences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(evidences, list):
        raise MemoryConsolidationError(
            "evidences deve ser uma lista."
        )

    if not evidences:
        raise MemoryConsolidationError(
            "Um Claim precisa de pelo menos uma evidência."
        )

    return evidences


def _calculate_evidence_balance(
    evidences: list[dict[str, Any]],
) -> tuple[
    int,
    int,
    float,
    float,
    float,
]:
    supporting_count = 0
    contradicting_count = 0

    supporting_weight = 0.0
    contradicting_weight = 0.0

    for evidence in evidences:
        role = evidence["evidence_role"]
        weight = float(evidence["weight"])

        if role == "supporting":
            supporting_count += 1
            supporting_weight += weight

        elif role == "contradicting":
            contradicting_count += 1
            contradicting_weight += weight

    total_weight = (
        supporting_weight
        + contradicting_weight
    )

    if total_weight <= 0:
        raise MemoryConsolidationError(
            "A soma dos pesos das evidências deve ser positiva."
        )

    evidence_balance = (
        supporting_weight / total_weight
    )

    return (
        supporting_count,
        contradicting_count,
        round(supporting_weight, 4),
        round(contradicting_weight, 4),
        round(evidence_balance, 4),
    )


def _calculate_consolidated_confidence(
    claim: MemoryClaim,
    evidence_balance: float,
) -> float:
    confidence = (
        claim.confidence
        * evidence_balance
    )

    return round(
        max(0.0, min(10.0, confidence)),
        4,
    )


def consolidate_claim_to_memory(
    *,
    claim_id: int,
    claim: MemoryClaim,
    evidences: list[dict[str, Any]],
) -> MemoryConsolidationResult:
    """
    Consolida um Claim validado em memória semântica.

    A operação é determinística e não acessa banco,
    rede ou modelos externos.
    """

    if (
        not isinstance(claim_id, int)
        or isinstance(claim_id, bool)
        or claim_id <= 0
    ):
        raise MemoryConsolidationError(
            "claim_id deve ser um inteiro positivo."
        )

    if claim.status not in VALID_CONSOLIDATION_STATUSES:
        raise MemoryConsolidationError(
            "Somente Claims active ou uncertain "
            "podem ser consolidados."
        )

    normalized_evidences = _validate_evidence(
        evidences
    )

    (
        supporting_count,
        contradicting_count,
        supporting_weight,
        contradicting_weight,
        evidence_balance,
    ) = _calculate_evidence_balance(
        normalized_evidences
    )

    consolidated_confidence = (
        _calculate_consolidated_confidence(
            claim,
            evidence_balance,
        )
    )

    memory = Memory(
        memory_type="semantic",
        content=claim.claim,
        source_type="memory_claim",
        source_id=str(claim_id),
        confidence=consolidated_confidence,
        importance=claim.confidence,
        scope=claim.scope,
        valid_at=claim.valid_at,
        invalid_at=claim.invalid_at,
    )

    return MemoryConsolidationResult(
        claim_id=claim_id,
        memory=memory,
        supporting_evidence_count=supporting_count,
        contradicting_evidence_count=contradicting_count,
        supporting_weight=supporting_weight,
        contradicting_weight=contradicting_weight,
        evidence_balance=evidence_balance,
    )


def consolidation_to_dict(
    result: MemoryConsolidationResult,
) -> dict[str, Any]:
    """Serializa o resultado da consolidação."""

    return {
        "claim_id": result.claim_id,
        "memory": result.memory,
        "supporting_evidence_count": (
            result.supporting_evidence_count
        ),
        "contradicting_evidence_count": (
            result.contradicting_evidence_count
        ),
        "supporting_weight": (
            result.supporting_weight
        ),
        "contradicting_weight": (
            result.contradicting_weight
        ),
        "evidence_balance": (
            result.evidence_balance
        ),
    }
