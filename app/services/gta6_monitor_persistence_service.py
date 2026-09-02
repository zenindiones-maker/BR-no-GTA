from __future__ import annotations

from dataclasses import dataclass

from app.database.gta6_monitor_repository import (
    get_gta6_monitor_state,
    save_gta6_monitor_state,
)
from app.integrations.gta6.vice_monitor import GTA6ViceMonitor
from app.services.gta6_change_detector import (
    GTA6ChangeResult,
    detect_content_change,
)
from app.services.gta6_monitor_event_service import (
    record_gta6_monitor_change,
)


@dataclass(frozen=True)
class GTA6PersistentMonitorResult:
    url: str
    status_code: int
    change: GTA6ChangeResult
    baseline: bool


def monitor_gta6_page_persisted(
    monitor: GTA6ViceMonitor,
    url: str,
) -> GTA6PersistentMonitorResult:
    if not isinstance(monitor, GTA6ViceMonitor):
        raise ValueError(
            "monitor must be a GTA6ViceMonitor"
        )

    previous_state = get_gta6_monitor_state(url)

    previous_hash = (
        previous_state["content_hash"]
        if previous_state is not None
        else None
    )

    page = monitor.fetch(url)

    change = detect_content_change(
        page.content,
        previous_hash,
    )

    baseline = previous_hash is None

    save_gta6_monitor_state(
        page.url,
        change.current_hash,
    )

    if not baseline and change.changed:
        record_gta6_monitor_change(
            url=page.url,
            previous_hash=change.previous_hash,
            current_hash=change.current_hash,
        )

    return GTA6PersistentMonitorResult(
        url=page.url,
        status_code=page.status_code,
        change=change,
        baseline=baseline,
    )
