from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from app.contracts.youtube_intelligence_contracts import YouTubePolicySnapshot


DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "youtube_policy_snapshots_v1.json"
)


def _canonical_policy_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "policy_id",
            "policy_family",
            "source_url",
            "observed_at",
            "effective_from",
            "effective_until",
            "jurisdiction_or_market",
            "structured_values",
            "status",
        )
    }


def _digest_policy_payload(item: dict[str, Any]) -> str:
    raw = json.dumps(
        _canonical_policy_payload(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def load_policy_snapshots(path: str | Path | None = None) -> tuple[YouTubePolicySnapshot, ...]:
    source = Path(path) if path is not None else DEFAULT_POLICY_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema") != "YouTubePolicyRegistry/v1":
        raise ValueError("invalid YouTube policy registry schema")
    if payload.get("generated_from_official_sources_only") is not True:
        raise ValueError("YouTube policy registry must be official-source-only")
    snapshots: list[YouTubePolicySnapshot] = []
    for raw in payload.get("snapshots") or ():
        if not isinstance(raw, dict):
            raise ValueError("YouTube policy snapshot must be an object")
        expected = _digest_policy_payload(raw)
        if raw.get("content_digest") != expected:
            raise ValueError(
                "YouTube policy snapshot digest mismatch: "
                + str(raw.get("policy_id") or "UNKNOWN")
            )
        snapshot = YouTubePolicySnapshot(
            policy_id=str(raw.get("policy_id") or ""),
            policy_family=str(raw.get("policy_family") or ""),
            source_url=str(raw.get("source_url") or ""),
            observed_at=str(raw.get("observed_at") or ""),
            effective_from=str(raw.get("effective_from") or ""),
            effective_until=raw.get("effective_until"),
            jurisdiction_or_market=raw.get("jurisdiction_or_market"),
            structured_values=dict(raw.get("structured_values") or {}),
            content_digest=expected,
            status=str(raw.get("status") or "CURRENT"),
            evidence_refs=(str(raw.get("source_url") or ""),),
        )
        if not snapshot.policy_id or not snapshot.policy_family or not snapshot.source_url:
            raise ValueError("YouTube policy snapshot identity incomplete")
        snapshots.append(snapshot)
    if not snapshots:
        raise ValueError("YouTube policy registry is empty")
    return tuple(snapshots)


def _as_date(value: date | datetime | str | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def current_policy_snapshot(
    policy_family: str,
    *,
    on_date: date | datetime | str | None = None,
    snapshots: Iterable[YouTubePolicySnapshot] | None = None,
) -> YouTubePolicySnapshot:
    family = str(policy_family or "").strip().upper()
    if not family:
        raise ValueError("policy_family is required")
    target = _as_date(on_date)
    candidates: list[YouTubePolicySnapshot] = []
    for item in snapshots or load_policy_snapshots():
        if item.policy_family != family:
            continue
        start = date.fromisoformat(item.effective_from)
        end = date.fromisoformat(item.effective_until) if item.effective_until else None
        if start <= target and (end is None or target <= end):
            candidates.append(item)
    if not candidates:
        raise LookupError(f"no effective YouTube policy snapshot for {family} on {target}")
    candidates.sort(key=lambda item: (item.effective_from, item.observed_at, item.policy_id))
    return candidates[-1]


def policy_ref(snapshot: YouTubePolicySnapshot) -> str:
    return f"youtube-policy:{snapshot.policy_id}:{snapshot.content_digest}"


def policy_registry_projection() -> tuple[dict[str, Any], ...]:
    return tuple(asdict(item) for item in load_policy_snapshots())


__all__ = [
    "DEFAULT_POLICY_PATH",
    "load_policy_snapshots",
    "current_policy_snapshot",
    "policy_ref",
    "policy_registry_projection",
]
