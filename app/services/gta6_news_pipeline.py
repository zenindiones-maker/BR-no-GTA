from typing import Any

from app.integrations.gta6.news_feeds import fetch_gta6_news_feeds
from app.services.gta6_news_ingestion import ingest_gta6_news_items


def run_gta6_news_pipeline(
    *,
    timeout: int = 20,
) -> list[dict[str, Any]]:
    """Busca notícias GTA 6 e persiste os itens encontrados."""
    items = fetch_gta6_news_feeds(timeout=timeout)

    if not items:
        return []

    return ingest_gta6_news_items(items)
