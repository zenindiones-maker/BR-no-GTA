from typing import Any

from app.integrations.gta6.rockstar_newswire_graph import (
    RockstarNewswireGraphClient,
)
from app.integrations.gta6.rockstar_newswire_source import (
    fetch_rockstar_newswire_source,
)
from app.services.gta6_ingestion import (
    ingest_gta6_source_items,
)


def ingest_rockstar_newswire(
    query_hash: str,
) -> list[dict[str, Any]]:
    """Busca o Rockstar Newswire via Graph e persiste os itens GTA 6."""

    client = RockstarNewswireGraphClient(query_hash)

    items = fetch_rockstar_newswire_source(client)

    if not items:
        return []

    return ingest_gta6_source_items(items)
