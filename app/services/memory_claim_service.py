from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MemoryClaimError(ValueError):
    """Erro de domínio de claims da memória."""


VALID_CLAIM_TYPES = {
    "fact",
    "observation",
    "interpretation",
    "prediction",
}


VALID_CLAIM_STATUSES = {
    "active",
    "uncertain",
    "superseded",
    "rejected",
}


@dataclass(frozen=True)
class MemoryClaim:
    """Afirmação derivada de uma ou mais evidências."""

    claim: str
    claim_type: str
    confidence: float
    status: str
    scope: str
    valid_at: str | None
    invalid_at: str | None
    extraction_method: str


def _validate_score(
    value: float,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise MemoryClaimError(
            f"{field_name} deve ser numérico."
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise MemoryClaimError(
            f"{field_name} deve ser numérico."
        ) from exc

    if not 0.0 <= normalized <= 10.0:
        raise MemoryClaimError(
            f"{field_name} deve estar entre 0 e 10."
        )

    return round(normalized, 2)


def create_memory_claim(
    *,
    claim: str,
    claim_type: str = "fact",
    confidence: float = 5.0,
    status: str = "active",
    scope: str = "gta6",
    valid_at: str | None = None,
    invalid_at: str | None = None,
    extraction_method: str = "manual",
) -> MemoryClaim:
    """Cria um claim sem acessar banco, rede ou modelos."""

    if (
        not isinstance(claim, str)
        or not claim.strip()
    ):
        raise MemoryClaimError(
            "claim é obrigatório."
        )

    if claim_type not in VALID_CLAIM_TYPES:
        raise MemoryClaimError(
            f"Tipo de claim inválido: {claim_type}"
        )

    if status not in VALID_CLAIM_STATUSES:
        raise MemoryClaimError(
            f"Status de claim inválido: {status}"
        )

    if (
        not isinstance(scope, str)
        or not scope.strip()
    ):
        raise MemoryClaimError(
            "scope é obrigatório."
        )

    if (
        not isinstance(extraction_method, str)
        or not extraction_method.strip()
    ):
        raise MemoryClaimError(
            "extraction_method é obrigatório."
        )

    normalized_confidence = _validate_score(
        confidence,
        "confidence",
    )

    if (
        valid_at is not None
        and not isinstance(valid_at, str)
    ):
        raise MemoryClaimError(
            "valid_at deve ser uma string ou None."
        )

    if (
        invalid_at is not None
        and not isinstance(invalid_at, str)
    ):
        raise MemoryClaimError(
            "invalid_at deve ser uma string ou None."
        )

    if valid_at and invalid_at:
        if invalid_at < valid_at:
            raise MemoryClaimError(
                "invalid_at não pode ser anterior a valid_at."
            )

    return MemoryClaim(
        claim=claim.strip(),
        claim_type=claim_type,
        confidence=normalized_confidence,
        status=status,
        scope=scope.strip(),
        valid_at=valid_at,
        invalid_at=invalid_at,
        extraction_method=extraction_method.strip(),
    )


def claim_to_dict(
    claim: MemoryClaim,
) -> dict[str, Any]:
    """Serializa um claim sem depender da persistência."""

    return {
        "claim": claim.claim,
        "claim_type": claim.claim_type,
        "confidence": claim.confidence,
        "status": claim.status,
        "scope": claim.scope,
        "valid_at": claim.valid_at,
        "invalid_at": claim.invalid_at,
        "extraction_method": claim.extraction_method,
    }
