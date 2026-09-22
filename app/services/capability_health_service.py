from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.provider_health_service import provider_health


HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
BLOCKED = "BLOCKED"
QUARANTINED = "QUARANTINED"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CapabilityHealth:
    capability_id: str
    state: str
    reason: str
    retry_allowed: bool
    confidence: float
    sample_size: int
    last_success_at: str | None
    last_failure_at: str | None
    evidence_refs: tuple[str, ...]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _episodes(capability_id: str) -> list[dict[str, Any]]:
    try:
        return learning_repository.list_episodes(
            capability_id=capability_id,
            limit=80,
        )
    except Exception:
        return []


def _failure_memories(capability_id: str) -> list[dict[str, Any]]:
    try:
        return learning_repository.list_memories(
            status="ACTIVE",
            memory_type="FAILURE",
            capability_id=capability_id,
            limit=20,
        )
    except Exception:
        return []


def capability_health(capability_id: str) -> CapabilityHealth:
    record = GLOBAL_CAPABILITY_REGISTRY.get(str(capability_id or "").strip())
    if record is None:
        return CapabilityHealth(
            capability_id=str(capability_id or ""),
            state=BLOCKED,
            reason="Capability is absent from the canonical Registry.",
            retry_allowed=False,
            confidence=1.0,
            sample_size=0,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=(),
            source="REGISTRY",
        )
    if not record.execution_enabled:
        return CapabilityHealth(
            capability_id=record.capability_id,
            state=BLOCKED if not record.available else UNKNOWN,
            reason=(
                f"Registry availability={record.availability}; "
                f"executor_binding={'present' if record.executor_binding else 'missing'}."
            ),
            retry_allowed=False,
            confidence=1.0,
            sample_size=0,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=(),
            source="REGISTRY",
        )

    # Provider health is authoritative for externally backed executors when the
    # provider has a registered health boundary. Internal/native records are
    # assessed from execution evidence instead.
    provider_id = str(record.provider_id or "").strip()
    if provider_id and provider_id not in {"internal", "native"}:
        try:
            ph = provider_health(provider_id)
        except Exception:
            ph = None
        if ph is not None and ph.state in {
            "BLOCKED", "UPSTREAM_DENIED", "QUARANTINED", "AUTH_REQUIRED",
        }:
            mapped = QUARANTINED if ph.state == "QUARANTINED" else BLOCKED
            return CapabilityHealth(
                capability_id=record.capability_id,
                state=mapped,
                reason=ph.reason,
                retry_allowed=bool(ph.retry_allowed),
                confidence=0.95,
                sample_size=0,
                last_success_at=None,
                last_failure_at=None,
                evidence_refs=tuple(ph.evidence_refs),
                source="PROVIDER_HEALTH",
            )

    episodes = _episodes(record.capability_id)
    successes = [
        item for item in episodes
        if str(item.get("status") or "").upper()
        in {"PASS", "SUCCESS", "SUCCEEDED", "COMPLETED"}
    ]
    failures = [
        item for item in episodes
        if str(item.get("status") or "").upper()
        in {"FAIL", "FAILURE", "FAILED", "BLOCKED", "ERROR"}
    ]
    latest_success = max(
        (_parse_time(item.get("finished_at") or item.get("created_at")) for item in successes),
        default=None,
    )
    latest_failure = max(
        (_parse_time(item.get("finished_at") or item.get("created_at")) for item in failures),
        default=None,
    )
    failure_memories = _failure_memories(record.capability_id)
    strongest_failure = max(
        failure_memories,
        key=lambda item: float(item.get("confidence") or 0.0),
        default=None,
    )
    failure_confidence = float(
        (strongest_failure or {}).get("confidence") or 0.0
    )
    refs = tuple(dict.fromkeys(
        str(ref)
        for item in [*episodes[:10], *failure_memories[:5]]
        for ref in (item.get("evidence_refs") or ())
        if str(ref)
    ))

    if str(record.health_policy or "") == "CODEX_AUTH_REQUIRED":
        # Historical login state is not treated as a current credential. The
        # cloud execution boundary must run the real noninteractive auth
        # preflight immediately before a write-capable execution.
        return CapabilityHealth(
            capability_id=record.capability_id,
            state=UNKNOWN,
            reason=(
                "Current Codex authentication must be proven on the executing "
                "runner before this capability can be treated as healthy."
            ),
            retry_allowed=False,
            confidence=max(0.5, failure_confidence),
            sample_size=len(episodes),
            last_success_at=(
                latest_success.isoformat() if latest_success else None
            ),
            last_failure_at=(
                latest_failure.isoformat() if latest_failure else None
            ),
            evidence_refs=refs,
            source="CODEX_AUTH_PREFLIGHT_REQUIRED",
        )

    if (
        strongest_failure is not None
        and failure_confidence >= 0.8
        and (latest_success is None or (
            latest_failure is not None and latest_failure >= latest_success
        ))
    ):
        retry_allowed = bool(record.supports_retry) and failure_confidence < 0.95
        return CapabilityHealth(
            capability_id=record.capability_id,
            state=BLOCKED if failure_confidence >= 0.9 else DEGRADED,
            reason=str(
                strongest_failure.get("failure_pattern")
                or strongest_failure.get("claim")
                or "High-confidence active failure memory."
            )[:500],
            retry_allowed=retry_allowed,
            confidence=failure_confidence,
            sample_size=len(episodes),
            last_success_at=(
                latest_success.isoformat() if latest_success else None
            ),
            last_failure_at=(
                latest_failure.isoformat() if latest_failure else None
            ),
            evidence_refs=refs,
            source="LEARNING_FAILURE_MEMORY",
        )

    if latest_success is not None:
        return CapabilityHealth(
            capability_id=record.capability_id,
            state=HEALTHY if latest_failure is None or latest_success >= latest_failure else DEGRADED,
            reason="Recent execution evidence includes a successful completion.",
            retry_allowed=bool(record.supports_retry),
            confidence=min(0.98, 0.55 + 0.04 * len(episodes)),
            sample_size=len(episodes),
            last_success_at=latest_success.isoformat(),
            last_failure_at=(
                latest_failure.isoformat() if latest_failure else None
            ),
            evidence_refs=refs,
            source="HARNESS_EPISODES",
        )

    return CapabilityHealth(
        capability_id=record.capability_id,
        state=UNKNOWN,
        reason="No sufficient recent execution evidence exists.",
        retry_allowed=bool(record.supports_retry),
        confidence=0.25,
        sample_size=len(episodes),
        last_success_at=None,
        last_failure_at=(
            latest_failure.isoformat() if latest_failure else None
        ),
        evidence_refs=refs,
        source="REGISTRY_PLUS_LEARNING",
    )
