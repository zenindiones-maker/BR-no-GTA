from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.memory_claim_repository import (
    find_memory_claim_by_canonical_key,
    insert_memory_claim,
)
from app.services.memory_claim_service import MemoryClaim


class MemoryClaimResolutionError(ValueError):
    """Erro de resolução de identidade de Claim."""


@dataclass(frozen=True)
class MemoryClaimResolutionResult:
    action: str
    claim_id: int | None
    claim: MemoryClaim
    existing_claim: dict[str, Any] | None = None


VALID_RESOLUTION_ACTIONS = {
    "new",
    "reobserved",
}


def resolve_memory_claim(
    claim: MemoryClaim,
) -> MemoryClaimResolutionResult:
    """
    Resolve a identidade de um Claim antes da persistência.

    A identidade é determinada pelo canonical_key produzido
    pelo domínio. Claims com a mesma identidade não são duplicados.
    """

    if not isinstance(claim, MemoryClaim):
        raise TypeError(
            "claim deve ser uma instância de MemoryClaim."
        )

    existing = find_memory_claim_by_canonical_key(
        claim.canonical_key
    )

    if existing is not None:
        return MemoryClaimResolutionResult(
            action="reobserved",
            claim_id=int(existing["id"]),
            claim=claim,
            existing_claim=existing,
        )

    claim_id = insert_memory_claim(claim)

    if not isinstance(claim_id, int) or claim_id <= 0:
        raise MemoryClaimResolutionError(
            "Persistência do novo Claim retornou um ID inválido."
        )

    return MemoryClaimResolutionResult(
        action="new",
        claim_id=claim_id,
        claim=claim,
        existing_claim=None,
    )
