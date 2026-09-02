from __future__ import annotations

from typing import Any

from app.integrations.gta6.rockstar_news import ROCKSTAR_NEWSWIRE_URL
from app.integrations.gta6.rockstar_newswire_adapter import (
    parse_rockstar_newswire_html,
)
from app.integrations.gta6.source import GTA6SourceItem
from app.integrations.gta6.vice_monitor import GTA6ViceMonitor
from app.services.gta6_ingestion import ingest_gta6_source_items
from app.services.gta6_monitor_persistence_service import (
    monitor_gta6_page_persisted,
)


def collect_rockstar_newswire_items(
    *,
    timeout: float = 15.0,
) -> list[GTA6SourceItem]:
    """Captura o Newswire e converte o HTML em itens de fonte."""

    monitor = GTA6ViceMonitor(timeout=timeout)

    result = monitor_gta6_page_persisted(
        monitor,
        ROCKSTAR_NEWSWIRE_URL,
    )

    return parse_rockstar_newswire_html(result.content)


def ingest_rockstar_newswire_from_monitor(
    *,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Captura o Newswire e persiste os artigos no Knowledge Core."""

    items = collect_rockstar_newswire_items(
        timeout=timeout,
    )

    if not items:
        return []

    return ingest_gta6_source_items(items)
