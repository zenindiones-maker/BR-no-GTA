from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.gta6_monitor_run_repository import (
    create_gta6_monitor_run,
    get_gta6_monitor_run,
    update_gta6_monitor_run,
)


GTA6_MONITOR_RUN_RUNNING = "RUNNING"
GTA6_MONITOR_RUN_COMPLETED = "COMPLETED"
GTA6_MONITOR_RUN_ERROR = "ERROR"


def _utc_now() -> str:
    """Retorna o instante atual em UTC no formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def _get_running_run(run_id: int) -> dict[str, Any]:
    """Retorna uma execução RUNNING ou rejeita a transição."""
    run = get_gta6_monitor_run(run_id)

    if run is None:
        raise ValueError(
            f"GTA6 monitor run {run_id} was not found"
        )

    if run["status"] != GTA6_MONITOR_RUN_RUNNING:
        raise ValueError(
            "Only RUNNING GTA6 monitor runs can be finalized"
        )

    return run


def start_gta6_monitor_run(
    *,
    url: str,
) -> dict[str, Any]:
    """Cria uma nova execução no estado RUNNING."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")

    return create_gta6_monitor_run(
        status=GTA6_MONITOR_RUN_RUNNING,
        started_at=_utc_now(),
        url=url.strip(),
    )


def complete_gta6_monitor_run(
    *,
    run_id: int,
    status_code: int,
    baseline: bool,
    items_found: int,
    items_ingested: int,
    items_duplicated: int,
) -> dict[str, Any]:
    """Transiciona uma execução RUNNING para COMPLETED."""
    _get_running_run(run_id)

    if not isinstance(status_code, int) or isinstance(status_code, bool):
        raise ValueError("status_code must be an integer")

    if not isinstance(baseline, bool):
        raise ValueError("baseline must be a boolean")

    for field_name, value in (
        ("items_found", items_found),
        ("items_ingested", items_ingested),
        ("items_duplicated", items_duplicated),
    ):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{field_name} must be an integer")

        if value < 0:
            raise ValueError(
                f"{field_name} must be greater than or equal to zero"
            )

    return update_gta6_monitor_run(
        run_id=run_id,
        status=GTA6_MONITOR_RUN_COMPLETED,
        finished_at=_utc_now(),
        status_code=status_code,
        baseline=baseline,
        items_found=items_found,
        items_ingested=items_ingested,
        items_duplicated=items_duplicated,
    )


def fail_gta6_monitor_run(
    *,
    run_id: int,
    error: str,
    status_code: int | None = None,
) -> dict[str, Any]:
    """Transiciona uma execução RUNNING para ERROR."""
    _get_running_run(run_id)

    if not isinstance(error, str) or not error.strip():
        raise ValueError("error must be a non-empty string")

    if status_code is not None:
        if not isinstance(status_code, int) or isinstance(status_code, bool):
            raise ValueError(
                "status_code must be an integer or None"
            )

    return update_gta6_monitor_run(
        run_id=run_id,
        status=GTA6_MONITOR_RUN_ERROR,
        finished_at=_utc_now(),
        status_code=status_code,
        error=error.strip(),
    )
