from typing import Any

from app.integrations.gta6.news_adapter import convert_news_items
from app.integrations.gta6.news_aggregator import GTA6NewsFeedItem
from app.services.gta6_ingestion import ingest_gta6_source_items


def ingest_gta6_news_items(
    items: list[GTA6NewsFeedItem],
) -> list[dict[str, Any]]:
    """Converte notícias agregadas e persiste como conhecimento GTA 6."""
    source_items = convert_news_items(items)
    if not source_items:
        return []

    return ingest_gta6_source_items(source_items)
