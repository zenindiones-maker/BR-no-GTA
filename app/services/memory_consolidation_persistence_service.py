from __future__ import annotations

from typing import Any

from app.database.memory_claim_evidence_repository import (
    list_memory_claim_evidence_for_claim,
)
from app.database.memory_claim_repository import (
    get_memory_claim,
)
from app.database.memory_record_claims_repository import (
    insert_memory_record_claim,
)
from app.database.memory_repository import (
    insert_memory,
    list_memories,
)
from app.services.memory_claim_service import (
    MemoryClaim,
)
from app.services.memory_consolidation_service import (
    MemoryConsolidationResult,
    consolidate_claim_to_memory,
)


class MemoryConsolidationPersistenceError(ValueError):
    """Erro da persistência da consolidação de memória."""


def _build_memory_claim(
    claim_data: dict[str, Any],
) -> MemoryClaim:
    """Reconstrói o domínio MemoryClaim a partir do SQLite."""

    return MemoryClaim(
        claim=claim_data["claim"],
        claim_type=claim_data["claim_type"],
        confidence=float(claim_data["confidence"]),
        status=claim_data["status"],
        scope=claim_data["scope"],
        valid_at=claim_data["valid_at"],
        invalid_at=claim_data["invalid_at"],
        extraction_method=claim_data["extraction_method"],
    )


def _find_existing_memory(
    claim_id: int,
) -> dict[str, Any] | None:
    """Busca a memória semântica já derivada do Claim."""

    memories = list_memories(
        memory_type="semantic",
        scope="gta6",
        status="active",
    )

    source_id = str(claim_id)

    for memory in memories:
        if (
            memory["source_type"] == "memory_claim"
            and memory["source_id"] == source_id
        ):
            return memory

    return None


def consolidate_and_persist_claim(
    claim_id: int,
) -> dict[str, Any]:
    """
    Consolida um Claim persistido em memória semântica persistente.

    A operação é idempotente por Claim:
    se a memória semântica derivada já existir,
    ela não será duplicada.
    """

    if (
        not isinstance(claim_id, int)
        or isinstance(claim_id, bool)
        or claim_id <= 0
    ):
        raise MemoryConsolidationPersistenceError(
            "claim_id deve ser um inteiro positivo."
        )

    claim_data = get_memory_claim(claim_id)

    if claim_data is None:
        raise MemoryConsolidationPersistenceError(
            f"Claim não encontrado: {claim_id}"
        )

    existing_memory = _find_existing_memory(claim_id)

    if existing_memory is not None:
        return {
            "status": "already_consolidated",
            "claim_id": claim_id,
            "memory_id": existing_memory["id"],
            "memory": existing_memory,
            "consolidation": None,
        }

    evidences = list_memory_claim_evidence_for_claim(
        claim_id
    )

    claim = _build_memory_claim(claim_data)

    consolidation = consolidate_claim_to_memory(
        claim_id=claim_id,
        claim=claim,
        evidences=evidences,
    )

    memory_id = insert_memory(
        consolidation.memory
    )

    relation_id = insert_memory_record_claim(
        memory_record_id=memory_id,
        claim_id=claim_id,
    )

    persisted_memory = next(
        (
            memory
            for memory in list_memories(
                memory_type="semantic",
                scope=claim.scope,
                status="active",
            )
            if memory["id"] == memory_id
        ),
        None,
    )

    if persisted_memory is None:
        raise MemoryConsolidationPersistenceError(
            "Memory Record não foi encontrado após persistência."
        )

    return {
        "status": "consolidated",
        "claim_id": claim_id,
        "memory_id": memory_id,
        "relation_id": relation_id,
        "memory": persisted_memory,
        "consolidation": consolidation,
    }
