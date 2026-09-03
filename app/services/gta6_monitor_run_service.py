from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.gta6_monitor_repository import (
    get_gta6_monitor_state,
    save_gta6_monitor_state,
)
from app.integrations.gta6.rockstar_newswire_adapter import (
    parse_rockstar_newswire_html,
)
from app.integrations.gta6.rockstar_news import (
    ROCKSTAR_NEWSWIRE_URL,
)
from app.integrations.gta6.vice_monitor import (
    GTA6ViceMonitor,
)
from app.services.gta6_change_detector import (
    GTA6ChangeResult,
    detect_content_change,
)
from app.services.gta6_ingestion import (
    ingest_gta6_source_items,
)


@dataclass(frozen=True)
class GTA6MonitorRunResult:
    """Resultado de uma execução real do monitor GTA 6."""

    url: str
    status_code: int
    change: GTA6ChangeResult
    baseline: bool
    items_found: int
    items_ingested: int
    items_duplicated: int
    knowledge_ids: list[int]


def run_gta6_monitor_once(
    *,
    timeout: float = 15.0,
) -> GTA6MonitorRunResult:
    """Executa um ciclo real do monitor Rockstar Newswire."""

    monitor = GTA6ViceMonitor(timeout=timeout)

    previous_state = get_gta6_monitor_state(
        ROCKSTAR_NEWSWIRE_URL,
    )

    previous_hash = (
        previous_state["content_hash"]
        if previous_state is not None
        else None
    )

    page = monitor.fetch(
        ROCKSTAR_NEWSWIRE_URL,
    )

    change = detect_content_change(
        page.content,
        previous_hash,
    )

    baseline = previous_hash is None

    if not change.changed:
        save_gta6_monitor_state(
            page.url,
            change.current_hash,
        )

        return GTA6MonitorRunResult(
            url=page.url,
            status_code=page.status_code,
            change=change,
            baseline=baseline,
            items_found=0,
            items_ingested=0,
            items_duplicated=0,
            knowledge_ids=[],
        )

    items = parse_rockstar_newswire_html(
        page.content,
    )

    ingestion_results = ingest_gta6_source_items(
        items,
    )

    knowledge_ids: list[int] = []
    duplicated = 0

    for result in ingestion_results:
        knowledge_id = result.get("knowledge_id")

        if isinstance(knowledge_id, int):
            knowledge_ids.append(knowledge_id)

        if result.get("duplicate") is True:
            duplicated += 1

    save_gta6_monitor_state(
        page.url,
        change.current_hash,
    )

    return GTA6MonitorRunResult(
        url=page.url,
        status_code=page.status_code,
        change=change,
        baseline=baseline,
        items_found=len(items),
        items_ingested=len(items) - duplicated,
        items_duplicated=duplicated,
        knowledge_ids=knowledge_ids,
    )
