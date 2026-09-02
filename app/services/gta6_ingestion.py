from typing import Any

from app.integrations.gta6.source import GTA6SourceItem
from app.services.gta6_knowledge_service import create_gta6_knowledge


def ingest_gta6_source_item(
    item: GTA6SourceItem,
) -> dict[str, Any]:
    """Persiste um item de fonte como conhecimento GTA 6."""

    result = create_gta6_knowledge(
        title=item.title,
        summary=item.summary,
        source_name=item.source_name,
        source_url=item.url,
        fact_type=item.fact_type,
        confidence=item.confidence,
        published_at=item.published_at,
    )

    return result


def ingest_gta6_source_items(
    items: list[GTA6SourceItem],
) -> list[dict[str, Any]]:
    """Persiste uma coleção de itens de fonte como conhecimento GTA 6."""

    return [
        ingest_gta6_source_item(item)
        for item in items
    ]
