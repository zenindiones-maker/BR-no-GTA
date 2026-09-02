from typing import Any

from app.database.gta6_knowledge_repository import (
    insert_gta6_knowledge,
)
from app.database.research_repository import (
    insert_research_item,
)
from app.services.gta6_knowledge import (
    GTA6_CONFIDENCE_LEVELS,
    GTA6_FACT_TYPES,
    create_gta6_knowledge_item,
)


def create_gta6_knowledge(
    *,
    title: str,
    summary: str,
    source_name: str,
    source_url: str,
    fact_type: str,
    confidence: str,
    published_at: str | None = None,
) -> dict[str, Any]:
    """Cria uma pesquisa e seu registro especializado de conhecimento GTA 6."""

    if fact_type not in GTA6_FACT_TYPES:
        raise ValueError(
            f"invalid GTA6 fact type: {fact_type}"
        )

    if confidence not in GTA6_CONFIDENCE_LEVELS:
        raise ValueError(
            f"invalid GTA6 confidence: {confidence}"
        )

    item = create_gta6_knowledge_item(
        title=title,
        summary=summary,
        source_name=source_name,
        source_url=source_url,
        fact_type=fact_type,
        confidence=confidence,
        published_at=published_at,
    )

    research_item_id = insert_research_item(
        source_id=None,
        title=item.title,
        content=item.summary,
        url=item.source_url,
        published_at=item.published_at,
    )

    knowledge_id = insert_gta6_knowledge(
        research_item_id=research_item_id,
        fact_type=item.fact_type,
        confidence=item.confidence,
    )

    return {
        "research_item_id": research_item_id,
        "knowledge_id": knowledge_id,
        "knowledge": item.to_dict(),
    }
