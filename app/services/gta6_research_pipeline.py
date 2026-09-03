from typing import Any

from app.services.gta6_news_pipeline import run_gta6_news_pipeline
from app.services.gta6_rockstar_monitor_service import (
    monitor_rockstar_newswire,
)
from app.services.gta6_rockstar_monitor_ingestion import (
    ingest_rockstar_newswire_from_monitor,
)
from app.services.gta6_source_ingestion import (
    ingest_rockstar_newswire,
)
from app.services.gta6_editorial_pipeline import (
    process_gta6_research_results,
)
from app.settings import settings


def run_gta6_research() -> dict[str, Any]:
    """Executa a pesquisa GTA 6 e encaminha os resultados ao editorial."""

    rockstar_monitor = monitor_rockstar_newswire()

    rockstar_items = ingest_rockstar_newswire_from_monitor()

    if settings.ROCKSTAR_QUERY_HASH:
        rockstar_items.extend(
            ingest_rockstar_newswire(
                settings.ROCKSTAR_QUERY_HASH
            )
        )

    news_items = run_gta6_news_pipeline()

    research_results = [
        *rockstar_items,
        *news_items,
    ]

    editorial = process_gta6_research_results(
        research_results,
    )

    return {
        "rockstar_monitor": rockstar_monitor,
        "rockstar_newswire": rockstar_items,
        "news_feeds": news_items,
        "total": len(rockstar_items) + len(news_items),
        "editorial": editorial,
    }
