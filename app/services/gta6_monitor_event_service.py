from __future__ import annotations

from typing import Any

from app.database.gta6_monitor_event_repository import (
    create_gta6_monitor_event as persist_gta6_monitor_event,
)
from app.services.gta6_monitor_event import (
    create_gta6_monitor_event as build_gta6_monitor_event,
)


def record_gta6_monitor_change(
    url: str,
    previous_hash: str | None,
    current_hash: str,
    detected_at: str | None = None,
) -> dict[str, Any]:
    event = build_gta6_monitor_event(
        url=url,
        previous_hash=previous_hash,
        current_hash=current_hash,
        detected_at=detected_at,
    )

    return persist_gta6_monitor_event(
        url=event.url,
        previous_hash=event.previous_hash,
        current_hash=event.current_hash,
        detected_at=event.detected_at,
    )
