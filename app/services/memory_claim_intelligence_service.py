from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.database.memory_claim_repository import list_memory_claims
from app.services.memory_claim_service import MemoryClaim


class MemoryClaimIntelligenceError(ValueError):
    """Erro na análise de inteligência entre Claims."""


@dataclass(frozen=True)
class MemoryClaimMatch:
    claim_id: int
    claim: str
    confidence: float
    status: str
    scope: str
    similarity: float
    relation: str


@dataclass(frozen=True)
class MemoryClaimIntelligenceResult:
    decision: str
    claim: MemoryClaim
    matches: tuple[MemoryClaimMatch, ...]


VALID_DECISIONS = {
    "same_claim",
    "related_claim",
    "new_claim",
}

VALID_RELATIONS = {
    "same_claim",
    "related_claim",
}


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.casefold()
    normalized = re.sub(r"\s+", " ", normalized.strip())
    return normalized


def _tokenize(value: str) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()

    return set(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _calculate_similarity(
    left: str,
    right: str,
) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)

    if not left_tokens or not right_tokens:
        return 0.0

    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens

    if not union:
        return 0.0

    return round(len(intersection) / len(union), 4)


def _classify_relation(
    similarity: float,
) -> str | None:
    if similarity >= 0.85:
        return "same_claim"

    if similarity >= 0.35:
        return "related_claim"

    return None


def _validate_claim(claim: MemoryClaim) -> None:
    if not isinstance(claim, MemoryClaim):
        raise TypeError(
            "claim deve ser uma instância de MemoryClaim."
        )


def _build_match(
    row: dict[str, Any],
    similarity: float,
    relation: str,
) -> MemoryClaimMatch:
    claim_id = row.get("id")

    if not isinstance(claim_id, int) or claim_id <= 0:
        raise MemoryClaimIntelligenceError(
            "Claim persistido possui ID inválido."
        )

    return MemoryClaimMatch(
        claim_id=claim_id,
        claim=str(row["claim"]),
        confidence=float(row["confidence"]),
        status=str(row["status"]),
        scope=str(row["scope"]),
        similarity=similarity,
        relation=relation,
    )


def analyze_memory_claim(
    claim: MemoryClaim,
    *,
    limit: int = 5,
) -> MemoryClaimIntelligenceResult:
    """
    Analisa um Claim novo contra o conhecimento persistido.

    Esta camada não declara contradições semanticamente.
    Ela identifica identidade ou relação lexical suficientemente
    forte para alimentar uma etapa posterior de análise.
    """

    _validate_claim(claim)

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise MemoryClaimIntelligenceError(
            "limit deve ser um inteiro positivo."
        )

    existing_claims = list_memory_claims(
        scope=claim.scope,
        status="active",
        limit=max(limit * 10, 50),
    )

    matches: list[MemoryClaimMatch] = []

    for row in existing_claims:
        existing_canonical_key = str(
            row.get("canonical_key", "")
        ).strip()

        if (
            existing_canonical_key
            and existing_canonical_key == claim.canonical_key
        ):
            matches.append(
                _build_match(
                    row=row,
                    similarity=1.0,
                    relation="same_claim",
                )
            )
            continue

        similarity = _calculate_similarity(
            claim.claim,
            str(row["claim"]),
        )

        relation = _classify_relation(similarity)

        if relation is None:
            continue

        matches.append(
            _build_match(
                row=row,
                similarity=similarity,
                relation=relation,
            )
        )

    matches.sort(
        key=lambda match: (
            -match.similarity,
            -match.confidence,
            match.claim_id,
        )
    )

    matches = matches[:limit]

    if any(
        match.relation == "same_claim"
        for match in matches
    ):
        decision = "same_claim"
    elif matches:
        decision = "related_claim"
    else:
        decision = "new_claim"

    return MemoryClaimIntelligenceResult(
        decision=decision,
        claim=claim,
        matches=tuple(matches),
    )


def claim_intelligence_to_dict(
    result: MemoryClaimIntelligenceResult,
) -> dict[str, Any]:
    return {
        "decision": result.decision,
        "claim": {
            "claim": result.claim.claim,
            "canonical_key": result.claim.canonical_key,
            "claim_type": result.claim.claim_type,
            "confidence": result.claim.confidence,
            "status": result.claim.status,
            "scope": result.claim.scope,
            "valid_at": result.claim.valid_at,
            "invalid_at": result.claim.invalid_at,
            "extraction_method": result.claim.extraction_method,
        },
        "matches": [
            {
                "claim_id": match.claim_id,
                "claim": match.claim,
                "confidence": match.confidence,
                "status": match.status,
                "scope": match.scope,
                "similarity": match.similarity,
                "relation": match.relation,
            }
            for match in result.matches
        ],
    }
