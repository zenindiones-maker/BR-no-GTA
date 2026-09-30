from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
from typing import Any

from app.database.youtube_intelligence_repository import reserve_quota


@dataclass(frozen=True)
class YouTubeQuotaBudget:
    api: str
    operation: str
    estimated_unit_cost: int
    consumed: int
    remaining: int | None
    priority: int
    cache_state: str
    budget_date: str
    hard_limit: int | None
    schema: str = "YouTubeQuotaBudget/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Official defaults are deliberately conservative and can be overridden by
# deployment policy. search.list and videos.insert have dedicated daily request
# buckets; other Data API methods consume the standard daily unit allocation.
OFFICIAL_DEFAULT_LIMITS = {
    ("youtube_data", "search.list"): 100,
    ("youtube_data", "videos.insert"): 100,
    ("youtube_data", "general_units"): 10_000,
}

DATA_API_UNIT_COSTS = {
    "activities.list": 1,
    "channels.list": 1,
    "comments.list": 1,
    "commentThreads.list": 1,
    "playlistItems.list": 1,
    "playlists.list": 1,
    "search.list": 1,
    "videos.list": 1,
    "videos.insert": 1,
    "videos.update": 50,
    "thumbnails.set": 50,
    "playlistItems.insert": 50,
    "comments.insert": 50,
    "commentThreads.insert": 50,
}


def quota_cost(api: str, operation: str) -> int:
    if api == "youtube_data":
        if operation not in DATA_API_UNIT_COSTS:
            raise ValueError(f"unknown YouTube Data API quota cost for {operation}")
        return DATA_API_UNIT_COSTS[operation]
    # Analytics/Reporting do not share the Data API unit accounting model.
    if api in {"youtube_analytics", "youtube_reporting"}:
        return 1
    raise ValueError(f"unknown YouTube API family: {api}")


def _request_digest(payload: dict[str, Any]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def consume_quota(
    *,
    api: str,
    operation: str,
    request_identity: dict[str, Any],
    cache_state: str,
    priority: int = 50,
    hard_limit: int | None = None,
    budget_date: str | None = None,
) -> YouTubeQuotaBudget:
    if cache_state == "HIT":
        estimated = 0
    else:
        estimated = quota_cost(api, operation)
    day = budget_date or date.today().isoformat()
    if hard_limit is None:
        hard_limit = OFFICIAL_DEFAULT_LIMITS.get((api, operation))
        if hard_limit is None and api == "youtube_data":
            hard_limit = OFFICIAL_DEFAULT_LIMITS[("youtube_data", "general_units")]
    row = reserve_quota(
        api=api,
        operation=operation,
        budget_date=day,
        estimated_unit_cost=estimated,
        hard_limit=hard_limit,
        priority=int(priority),
        cache_state=cache_state,
        request_digest=_request_digest(request_identity),
    )
    return YouTubeQuotaBudget(
        api=row["api"],
        operation=row["operation"],
        estimated_unit_cost=int(row["estimated_unit_cost"]),
        consumed=int(row["consumed"]),
        remaining=row["remaining"],
        priority=int(row["priority"]),
        cache_state=row["cache_state"],
        budget_date=row["budget_date"],
        hard_limit=row["hard_limit"],
    )
