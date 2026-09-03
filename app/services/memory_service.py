from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MemoryError(ValueError):
    """Erro de domínio do sistema de memória."""


VALID_MEMORY_TYPES = {
    "episodic",
    "semantic",
    "procedural",
}


@dataclass(frozen=True)
class Memory:
    """Memória persistente do Brain."""

    memory_type: str
    content: str
    source_type: str
    source_id: str | None
    confidence: float
    importance: float
    scope: str
    valid_at: str | None
    invalid_at: str | None


def _validate_score(
    value: float,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise MemoryError(
            f"{field_name} deve ser numérico."
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise MemoryError(
            f"{field_name} deve ser numérico."
        ) from exc

    if not 0.0 <= normalized <= 10.0:
        raise MemoryError(
            f"{field_name} deve estar entre 0 e 10."
        )

    return normalized


def create_memory(
    *,
    memory_type: str,
    content: str,
    source_type: str,
    source_id: str | None = None,
    confidence: float = 5.0,
    importance: float = 5.0,
    scope: str = "gta6",
    valid_at: str | None = None,
    invalid_at: str | None = None,
) -> Memory:
    """Cria uma memória de domínio sem acessar infraestrutura."""

    if memory_type not in VALID_MEMORY_TYPES:
        raise MemoryError(
            f"Tipo de memória inválido: {memory_type}"
        )

    if (
        not isinstance(content, str)
        or not content.strip()
    ):
        raise MemoryError(
            "content é obrigatório."
        )

    if (
        not isinstance(source_type, str)
        or not source_type.strip()
    ):
        raise MemoryError(
            "source_type é obrigatório."
        )

    if source_id is not None:
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
        ):
            raise MemoryError(
                "source_id deve ser uma string válida ou None."
            )

    if (
        not isinstance(scope, str)
        or not scope.strip()
    ):
        raise MemoryError(
            "scope é obrigatório."
        )

    normalized_confidence = _validate_score(
        confidence,
        "confidence",
    )

    normalized_importance = _validate_score(
        importance,
        "importance",
    )

    if (
        valid_at is not None
        and not isinstance(valid_at, str)
    ):
        raise MemoryError(
            "valid_at deve ser uma string ou None."
        )

    if (
        invalid_at is not None
        and not isinstance(invalid_at, str)
    ):
        raise MemoryError(
            "invalid_at deve ser uma string ou None."
        )

    if valid_at and invalid_at:
        if invalid_at < valid_at:
            raise MemoryError(
                "invalid_at não pode ser anterior a valid_at."
            )

    return Memory(
        memory_type=memory_type,
        content=content.strip(),
        source_type=source_type.strip(),
        source_id=(
            source_id.strip()
            if isinstance(source_id, str)
            else None
        ),
        confidence=round(
            normalized_confidence,
            2,
        ),
        importance=round(
            normalized_importance,
            2,
        ),
        scope=scope.strip(),
        valid_at=valid_at,
        invalid_at=invalid_at,
    )


def calculate_memory_activation(
    memory: Memory,
    *,
    recency_score: float = 5.0,
    access_score: float = 5.0,
) -> float:
    """Calcula a prioridade atual de recuperação da memória."""

    normalized_recency = _validate_score(
        recency_score,
        "recency_score",
    )

    normalized_access = _validate_score(
        access_score,
        "access_score",
    )

    activation = (
        memory.confidence * 0.30
        + memory.importance * 0.30
        + normalized_recency * 0.25
        + normalized_access * 0.15
    )

    return round(
        max(0.0, min(10.0, activation)),
        2,
    )


def memory_to_dict(
    memory: Memory,
) -> dict[str, Any]:
    """Serializa uma memória sem depender da persistência."""

    return {
        "memory_type": memory.memory_type,
        "content": memory.content,
        "source_type": memory.source_type,
        "source_id": memory.source_id,
        "confidence": memory.confidence,
        "importance": memory.importance,
        "scope": memory.scope,
        "valid_at": memory.valid_at,
        "invalid_at": memory.invalid_at,
    }
