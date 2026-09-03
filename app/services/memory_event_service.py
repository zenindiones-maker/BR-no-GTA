from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MemoryEventError(ValueError):
    """Erro de domínio de eventos de memória."""


@dataclass(frozen=True)
class MemoryEvent:
    """Evento imutável que alimenta a memória persistente do Brain."""

    event_type: str
    source_type: str
    source_id: str | None
    content: str
    scope: str
    occurred_at: str | None
    observed_at: str | None
    provenance: str
    metadata: dict[str, Any]


def create_memory_event(
    *,
    event_type: str,
    source_type: str,
    content: str,
    source_id: str | None = None,
    scope: str = "gta6",
    occurred_at: str | None = None,
    observed_at: str | None = None,
    provenance: str = "",
    metadata: dict[str, Any] | None = None,
) -> MemoryEvent:
    """Cria um evento de memória sem acessar banco ou rede."""

    if (
        not isinstance(event_type, str)
        or not event_type.strip()
    ):
        raise MemoryEventError(
            "event_type é obrigatório."
        )

    if (
        not isinstance(source_type, str)
        or not source_type.strip()
    ):
        raise MemoryEventError(
            "source_type é obrigatório."
        )

    if (
        not isinstance(content, str)
        or not content.strip()
    ):
        raise MemoryEventError(
            "content é obrigatório."
        )

    if source_id is not None:
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
        ):
            raise MemoryEventError(
                "source_id deve ser uma string válida ou None."
            )

    if (
        not isinstance(scope, str)
        or not scope.strip()
    ):
        raise MemoryEventError(
            "scope é obrigatório."
        )

    if (
        occurred_at is not None
        and not isinstance(occurred_at, str)
    ):
        raise MemoryEventError(
            "occurred_at deve ser uma string ou None."
        )

    if (
        observed_at is not None
        and not isinstance(observed_at, str)
    ):
        raise MemoryEventError(
            "observed_at deve ser uma string ou None."
        )

    if (
        not isinstance(provenance, str)
    ):
        raise MemoryEventError(
            "provenance deve ser uma string."
        )

    if metadata is not None:
        if not isinstance(metadata, dict):
            raise MemoryEventError(
                "metadata deve ser um dicionário ou None."
            )

        normalized_metadata = dict(metadata)
    else:
        normalized_metadata = {}

    return MemoryEvent(
        event_type=event_type.strip(),
        source_type=source_type.strip(),
        source_id=(
            source_id.strip()
            if isinstance(source_id, str)
            else None
        ),
        content=content.strip(),
        scope=scope.strip(),
        occurred_at=occurred_at,
        observed_at=observed_at,
        provenance=provenance.strip(),
        metadata=normalized_metadata,
    )


def memory_event_to_dict(
    event: MemoryEvent,
) -> dict[str, Any]:
    """Serializa um evento de memória."""

    return {
        "event_type": event.event_type,
        "source_type": event.source_type,
        "source_id": event.source_id,
        "content": event.content,
        "scope": event.scope,
        "occurred_at": event.occurred_at,
        "observed_at": event.observed_at,
        "provenance": event.provenance,
        "metadata": dict(event.metadata),
    }
