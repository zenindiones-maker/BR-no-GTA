from __future__ import annotations

from collections import Counter
from typing import Any

from app.database.editorial_repository import list_editorial_evaluations
from app.database.gta6_monitor_repository import get_gta6_monitor_state
from app.database.ideas_repository import list_ideas
from app.database.queue_repository import list_active_queue_items, list_queue_items
from app.database.research_repository import list_research_items
from app.database.scripts_repository import list_scripts
from app.database.video_repository import list_videos
from app.database.youtube_repository import list_youtube_publications


GTA6_NEWSWIRE_URL = "https://www.rockstargames.com/newswire"


def _status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(
        str(item.get("status", "unknown"))
        for item in items
    ))


def _field_counts(
    items: list[dict[str, Any]],
    field: str,
) -> dict[str, int]:
    return dict(Counter(
        str(item.get(field, "unknown"))
        for item in items
    ))


def build_gta6_observation() -> dict[str, Any]:
    research = list_research_items()
    ideas = list_ideas()
    editorial = list_editorial_evaluations()
    queue = list_queue_items()
    active_queue = list_active_queue_items()
    scripts = list_scripts()
    videos = list_videos()
    youtube = list_youtube_publications()
    monitor = get_gta6_monitor_state(GTA6_NEWSWIRE_URL)

    return {
        "domain": "GTA6",
        "source_of_truth": "BR SQLite + official BR repositories",
        "monitor": monitor,
        "research": {
            "count": len(research),
        },
        "ideas": {
            "count": len(ideas),
            "by_status": _status_counts(ideas),
        },
        "editorial": {
            "count": len(editorial),
            "by_decision": _field_counts(editorial, "decision"),
        },
        "queue": {
            "count": len(queue),
            "by_status": _status_counts(queue),
            "active_count": len(active_queue),
            "active_by_status": _status_counts(active_queue),
        },
        "scripts": {
            "count": len(scripts),
            "by_status": _status_counts(scripts),
        },
        "videos": {
            "count": len(videos),
            "by_status": _status_counts(videos),
        },
        "youtube": {
            "count": len(youtube),
            "by_status": _status_counts(youtube),
        },
    }
