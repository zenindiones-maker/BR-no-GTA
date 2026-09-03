from __future__ import annotations

from typing import Any

from app.database.memory_event_repository import (
    insert_memory_event,
)
from app.services.memory_event_service import (
    create_memory_event,
)


class GTA6KnowledgeMemoryIngestionError(ValueError):
    """Erro de ingestão do conhecimento GTA6 na memória."""


def _validate_knowledge_result(
    knowledge_result: dict[str, Any],
) -> None:
    """Valida o contrato mínimo produzido pela ingestão GTA6."""

    if not isinstance(knowledge_result, dict):
        raise GTA6KnowledgeMemoryIngestionError(
            "knowledge_result deve ser um dicionário."
        )

    required_fields = {
        "research_item_id",
        "knowledge_id",
        "knowledge",
        "duplicate",
    }

    missing_fields = required_fields.difference(
        knowledge_result
    )

    if missing_fields:
        raise GTA6KnowledgeMemoryIngestionError(
            "Contrato de conhecimento incompleto: "
            + ", ".join(sorted(missing_fields))
        )

    research_item_id = knowledge_result[
        "research_item_id"
    ]

    if (
        not isinstance(research_item_id, int)
        or isinstance(research_item_id, bool)
        or research_item_id <= 0
    ):
        raise GTA6KnowledgeMemoryIngestionError(
            "research_item_id inválido."
        )

    knowledge_id = knowledge_result["knowledge_id"]

    if (
        not isinstance(knowledge_id, int)
        or isinstance(knowledge_id, bool)
        or knowledge_id <= 0
    ):
        raise GTA6KnowledgeMemoryIngestionError(
            "knowledge_id inválido."
        )

    if not isinstance(
        knowledge_result["duplicate"],
        bool,
    ):
        raise GTA6KnowledgeMemoryIngestionError(
            "duplicate deve ser booleano."
        )


def build_gta6_knowledge_memory_event(
    knowledge_result: dict[str, Any],
) -> Any:
    """
    Constrói o evento de memória correspondente
    a um conhecimento GTA6 já ingerido.
    """

    _validate_knowledge_result(
        knowledge_result
    )

    knowledge = knowledge_result["knowledge"]

    if knowledge_result["duplicate"]:
        event_type = "knowledge_reobserved"
    else:
        event_type = "knowledge_ingested"

    if knowledge is None:
        content = (
            "Conhecimento GTA6 já existente foi "
            "reencontrado durante a ingestão."
        )
    else:
        title = str(
            knowledge.get("title", "")
        ).strip()

        summary = str(
            knowledge.get("summary", "")
        ).strip()

        if title and summary:
            content = f"{title}: {summary}"
        elif title:
            content = title
        elif summary:
            content = summary
        else:
            content = (
                "Conhecimento GTA6 ingerido sem "
                "título ou resumo disponível."
            )

    return create_memory_event(
        event_type=event_type,
        source_type="gta6_knowledge",
        source_id=str(
            knowledge_result["knowledge_id"]
        ),
        content=content,
        scope="gta6",
        occurred_at=(
            knowledge.get("published_at")
            if isinstance(knowledge, dict)
            else None
        ),
        provenance="gta6_knowledge_ingestion",
        metadata={
            "research_item_id": knowledge_result[
                "research_item_id"
            ],
            "knowledge_id": knowledge_result[
                "knowledge_id"
            ],
            "duplicate": knowledge_result[
                "duplicate"
            ],
        },
    )


def ingest_gta6_knowledge_memory_event(
    knowledge_result: dict[str, Any],
) -> int:
    """
    Persiste o evento de memória de um conhecimento GTA6.

    A função mantém o Knowledge existente como autoridade
    e apenas registra sua observação no Memory Event Log.
    """

    event = build_gta6_knowledge_memory_event(
        knowledge_result
    )

    return insert_memory_event(event)


def ingest_gta6_knowledge_memory_events(
    knowledge_results: list[dict[str, Any]],
) -> list[int]:
    """
    Registra os eventos de memória de uma coleção
    de conhecimentos GTA6.
    """

    if not isinstance(
        knowledge_results,
        list,
    ):
        raise GTA6KnowledgeMemoryIngestionError(
            "knowledge_results deve ser uma lista."
        )

    return [
        ingest_gta6_knowledge_memory_event(
            result
        )
        for result in knowledge_results
    ]
