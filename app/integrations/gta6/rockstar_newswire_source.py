from __future__ import annotations

from app.integrations.gta6.rockstar_newswire_adapter import (
    convert_rockstar_articles,
)
from app.integrations.gta6.rockstar_newswire_graph import (
    RockstarNewswireGraphClient,
)
from app.integrations.gta6.source import GTA6SourceItem


def fetch_rockstar_newswire_source(
    client: RockstarNewswireGraphClient,
) -> list[GTA6SourceItem]:
    payload = client.fetch()
    articles = client.parse_articles(payload)
    return convert_rockstar_articles(articles)
