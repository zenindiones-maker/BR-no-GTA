from typing import Any

from app.services.gta6_news_pipeline import run_gta6_news_pipeline
from app.services.gta6_source_ingestion import ingest_rockstar_newswire


def run_gta6_research() -> dict[str, Any]:
    """Executa as fontes de pesquisa GTA 6 disponíveis."""
    rockstar_items = ingest_rockstar_newswire()
    news_items = run_gta6_news_pipeline()

    return {
        "rockstar_newswire": rockstar_items,
        "news_feeds": news_items,
        "total": len(rockstar_items) + len(news_items),
    }
