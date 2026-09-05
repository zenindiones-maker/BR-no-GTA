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
from app.services.gta6_monitor_event_service import (
    record_gta6_monitor_change,
)
from app.services.gta6_monitor_execution_context import (
    GTA6MonitorExecutionContext,
)
from app.services.gta6_monitor_execution_error import (
    GTA6MonitorExecutionError,
)
from app.services.gta6_monitor_execution_result import (
    GTA6MonitorExecutionResult,
)
from app.services.gta6_monitor_run_lifecycle_service import (
    complete_gta6_monitor_run,
    fail_gta6_monitor_run,
    start_gta6_monitor_run,
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
) -> GTA6MonitorExecutionResult:
    """Executa um ciclo real do monitor Rockstar Newswire."""

    run = start_gta6_monitor_run(
        url=ROCKSTAR_NEWSWIRE_URL,
    )

    run_id = run["id"]
    execution_context = GTA6MonitorExecutionContext.create(
        job_id="gta6-monitor",
        run_id=run_id,
    )
    status_code: int | None = None

    try:
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

        status_code = page.status_code

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

            result = GTA6MonitorRunResult(
                url=page.url,
                status_code=page.status_code,
                change=change,
                baseline=baseline,
                items_found=0,
                items_ingested=0,
                items_duplicated=0,
                knowledge_ids=[],
            )

            complete_gta6_monitor_run(
                run_id=run_id,
                status_code=result.status_code,
                baseline=result.baseline,
                items_found=result.items_found,
                items_ingested=result.items_ingested,
                items_duplicated=result.items_duplicated,
            )

            return GTA6MonitorExecutionResult(
                context=execution_context,
                result=result,
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

        record_gta6_monitor_change(
            url=page.url,
            previous_hash=change.previous_hash,
            current_hash=change.current_hash,
        )

        save_gta6_monitor_state(
            page.url,
            change.current_hash,
        )

        monitor_result = GTA6MonitorRunResult(
            url=page.url,
            status_code=page.status_code,
            change=change,
            baseline=baseline,
            items_found=len(items),
            items_ingested=len(items) - duplicated,
            items_duplicated=duplicated,
            knowledge_ids=knowledge_ids,
        )

        complete_gta6_monitor_run(
            run_id=run_id,
            status_code=monitor_result.status_code,
            baseline=monitor_result.baseline,
            items_found=monitor_result.items_found,
            items_ingested=monitor_result.items_ingested,
            items_duplicated=monitor_result.items_duplicated,
        )

        return GTA6MonitorExecutionResult(
            context=execution_context,
            result=monitor_result,
        )

    except Exception as exc:
        fail_gta6_monitor_run(
            run_id=run_id,
            error=str(exc),
            status_code=status_code,
        )
        raise GTA6MonitorExecutionError(
            context=execution_context,
            cause=exc,
        ) from exc
