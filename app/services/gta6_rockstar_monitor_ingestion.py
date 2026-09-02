from __future__ import annotations

from app.integrations.gta6.rockstar_news import ROCKSTAR_NEWSWIRE_URL
from app.integrations.gta6.rockstar_newswire_adapter import (
    parse_rockstar_newswire_html,
)
from app.integrations.gta6.source import GTA6SourceItem
from app.integrations.gta6.vice_monitor import GTA6ViceMonitor
from app.services.gta6_monitor_persistence_service import (
    monitor_gta6_page_persisted,
)


def collect_rockstar_newswire_items(
    *,
    timeout: float = 15.0,
) -> list[GTA6SourceItem]:
    """Captura o Rockstar Newswire e converte o HTML em itens de fonte."""

    monitor = GTA6ViceMonitor(timeout=timeout)

    result = monitor_gta6_page_persisted(
        monitor,
        ROCKSTAR_NEWSWIRE_URL,
    )

    return parse_rockstar_newswire_html(result.content)
