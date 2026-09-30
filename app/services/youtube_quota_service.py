from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
from typing import Any

from app.database.youtube_intelligence_repository import reserve_quota
from app.services.youtube_policy_registry_service import current_policy_snapshot, policy_ref


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
    quota_bucket: str
    policy_id: str
    policy_digest: str
    reset_time: str | None
    pagination_cost: int
    schema: str = "YouTubeQuotaBudget/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def quota_policy(
    api: str,
    operation: str,
    *,
    on_date: date | str | None = None,
) -> dict[str, Any]:
    snapshot = current_policy_snapshot("API_QUOTA", on_date=on_date)
    api_name = str(api or "").strip()
    op = str(operation or "").strip()
    families = snapshot.structured_values.get("api_families") or {}
    family = families.get(api_name)
    if not isinstance(family, dict):
        raise ValueError(f"unknown YouTube API family: {api_name}")

    buckets = family.get("buckets") or {}
    bucket = buckets.get(op) or buckets.get("default")
    if not isinstance(bucket, dict):
        raise ValueError(f"no quota bucket policy for {api_name}:{op}")

    costs = family.get("operation_costs") or {}
    if op in bucket:
        operation_cost = bucket.get("operation_cost")
    else:
        operation_cost = costs.get(op, bucket.get("operation_cost"))
    if operation_cost is None:
        raise ValueError(f"unknown YouTube quota cost for {api_name}:{op}")

    return {
        "api": api_name,
        "operation": op,
        "quota_bucket": str(bucket.get("quota_bucket") or "UNKNOWN"),
        "hard_limit": bucket.get("hard_limit"),
        "operation_cost": int(operation_cost),
        "pagination_cost": int(bucket.get("pagination_cost", 1)),
        "reset_time": family.get("reset_time"),
        "policy_id": snapshot.policy_id,
        "policy_digest": snapshot.content_digest,
        "policy_ref": policy_ref(snapshot),
        "policy_source_url": snapshot.source_url,
    }


def quota_cost(api: str, operation: str) -> int:
    return int(quota_policy(api, operation)["operation_cost"])


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
    day = budget_date or date.today().isoformat()
    policy = quota_policy(api, operation, on_date=day)
    estimated = 0 if cache_state == "HIT" else int(policy["operation_cost"])
    effective_limit = policy["hard_limit"] if hard_limit is None else hard_limit
    row = reserve_quota(
        api=api,
        operation=operation,
        budget_date=day,
        estimated_unit_cost=estimated,
        hard_limit=effective_limit,
        priority=int(priority),
        cache_state=cache_state,
        request_digest=_request_digest(request_identity),
        quota_bucket=policy["quota_bucket"],
        policy_id=policy["policy_id"],
        policy_digest=policy["policy_digest"],
        reset_time=policy["reset_time"],
        pagination_cost=policy["pagination_cost"],
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
        quota_bucket=str(row.get("quota_bucket") or policy["quota_bucket"]),
        policy_id=str(row.get("policy_id") or policy["policy_id"]),
        policy_digest=str(row.get("policy_digest") or policy["policy_digest"]),
        reset_time=row.get("reset_time"),
        pagination_cost=int(row.get("pagination_cost") or policy["pagination_cost"]),
    )


__all__ = ["YouTubeQuotaBudget", "quota_policy", "quota_cost", "consume_quota"]
