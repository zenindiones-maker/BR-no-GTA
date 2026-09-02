from typing import Any

from app.integrations.gta6.rockstar_news import (
    fetch_rockstar_newswire,
)
from app.services.gta6_ingestion import (
    ingest_gta6_source_items,
)


def ingest_rockstar_newswire() -> list[dict[str, Any]]:
    """Busca o Rockstar Newswire e persiste os itens GTA 6."""

    items = fetch_rockstar_newswire()

    if not items:
        return []

    return ingest_gta6_source_items(items)
