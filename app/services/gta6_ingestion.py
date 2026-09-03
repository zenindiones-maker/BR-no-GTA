from typing import Any

from app.integrations.gta6.source import GTA6SourceItem
from app.database.gta6_knowledge_repository import get_gta6_knowledge_by_source_url
from app.services.gta6_knowledge_service import create_gta6_knowledge
from app.services.gta6_knowledge_memory_ingestion_service import (
    ingest_gta6_knowledge_memory_event,
)


def ingest_gta6_source_item(
    item: GTA6SourceItem,
) -> dict[str, Any]:
    """Persiste um item de fonte como conhecimento GTA 6."""

    existing = get_gta6_knowledge_by_source_url(item.url)

    if existing is not None:
        result = {
            "research_item_id": existing["research_item_id"],
            "knowledge_id": existing["id"],
            "knowledge": None,
            "duplicate": True,
        }

        ingest_gta6_knowledge_memory_event(result)

        return result

    result = create_gta6_knowledge(
        title=item.title,
        summary=item.summary,
        source_name=item.source_name,
        source_url=item.url,
        fact_type=item.fact_type,
        confidence=item.confidence,
        published_at=item.published_at,
    )

    result["duplicate"] = False

    ingest_gta6_knowledge_memory_event(result)

    return result


def ingest_gta6_source_items(
    items: list[GTA6SourceItem],
) -> list[dict[str, Any]]:
    """Persiste uma coleção de itens de fonte como conhecimento GTA 6."""

    return [
        ingest_gta6_source_item(item)
        for item in items
    ]
