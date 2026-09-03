from __future__ import annotations

from app.services.gta6_knowledge import (
    GTA6KnowledgeItem,
)
from app.services.memory_claim_service import (
    MemoryClaim,
    create_memory_claim,
)


def _map_confidence(confidence: str) -> float:
    mapping = {
        "confirmed": 9.0,
        "probable": 7.5,
        "unconfirmed": 5.0,
        "rumor": 3.0,
    }

    try:
        return mapping[confidence]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported GTA6 knowledge confidence: {confidence!r}"
        ) from exc


def extract_gta6_claims(
    knowledge: GTA6KnowledgeItem,
) -> list[MemoryClaim]:
    if not isinstance(knowledge, GTA6KnowledgeItem):
        raise TypeError(
            "knowledge must be a GTA6KnowledgeItem"
        )

    claim = create_memory_claim(
        claim=knowledge.summary.strip(),
        claim_type="observation",
        confidence=_map_confidence(knowledge.confidence),
        status="active",
        scope="gta6",
        valid_at=knowledge.published_at,
        extraction_method="gta6_knowledge",
    )

    return [claim]
