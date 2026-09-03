from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MemoryClaimEvidenceError(ValueError):
    """Erro de domínio da relação entre claim e evidência."""


VALID_EVIDENCE_ROLES = {
    "supporting",
    "contradicting",
    "context",
}


@dataclass(frozen=True)
class MemoryClaimEvidence:
    """Ligação imutável entre um Claim e um evento de evidência."""

    claim_id: int
    event_id: int
    evidence_role: str
    weight: float


def _validate_positive_id(
    value: int,
    field_name: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise MemoryClaimEvidenceError(
            f"{field_name} deve ser um inteiro positivo."
        )

    return value


def _validate_weight(
    value: float,
) -> float:
    if isinstance(value, bool):
        raise MemoryClaimEvidenceError(
            "weight deve ser numérico."
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise MemoryClaimEvidenceError(
            "weight deve ser numérico."
        ) from exc

    if not 0.0 <= normalized <= 1.0:
        raise MemoryClaimEvidenceError(
            "weight deve estar entre 0 e 1."
        )

    return round(normalized, 4)


def create_memory_claim_evidence(
    *,
    claim_id: int,
    event_id: int,
    evidence_role: str = "supporting",
    weight: float = 1.0,
) -> MemoryClaimEvidence:
    """
    Cria uma relação Claim ↔ Evidence.

    A relação não acessa banco, rede ou modelos.
    """

    normalized_claim_id = _validate_positive_id(
        claim_id,
        "claim_id",
    )

    normalized_event_id = _validate_positive_id(
        event_id,
        "event_id",
    )

    if evidence_role not in VALID_EVIDENCE_ROLES:
        raise MemoryClaimEvidenceError(
            f"Role de evidência inválida: {evidence_role}"
        )

    normalized_weight = _validate_weight(weight)

    return MemoryClaimEvidence(
        claim_id=normalized_claim_id,
        event_id=normalized_event_id,
        evidence_role=evidence_role,
        weight=normalized_weight,
    )


def claim_evidence_to_dict(
    evidence: MemoryClaimEvidence,
) -> dict[str, Any]:
    """Serializa uma relação Claim ↔ Evidence."""

    return {
        "claim_id": evidence.claim_id,
        "event_id": evidence.event_id,
        "evidence_role": evidence.evidence_role,
        "weight": evidence.weight,
    }
