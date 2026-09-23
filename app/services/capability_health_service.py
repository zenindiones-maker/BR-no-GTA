from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.provider_health_service import (
    provider_health,
    semantic_provider_health,
)


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


_RUNTIME_HEALTH_STATES = {
    HEALTHY,
    DEGRADED,
    BLOCKED,
    QUARANTINED,
    UNKNOWN,
}


def _runtime_health_override(capability_id: str) -> CapabilityHealth | None:
    raw = str(os.getenv("BR_RUNTIME_CAPABILITY_HEALTH_JSON") or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    item = payload.get(str(capability_id))
    if not isinstance(item, dict):
        return None
    state = str(item.get("state") or "").strip().upper()
    if state not in _RUNTIME_HEALTH_STATES:
        return None
    reason = str(item.get("reason") or "runtime capability health preflight").strip()
    refs = tuple(
        str(ref)
        for ref in (item.get("evidence_refs") or ())
        if str(ref).strip()
    )
    return CapabilityHealth(
        capability_id=str(capability_id),
        state=state,
        reason=reason[:500],
        retry_allowed=bool(item.get("retry_allowed", state in {HEALTHY, DEGRADED})),
        confidence=max(0.0, min(1.0, float(item.get("confidence") or 1.0))),
        sample_size=max(0, int(item.get("sample_size") or 0)),
        last_success_at=(
            str(item.get("last_success_at"))
            if item.get("last_success_at") else None
        ),
        last_failure_at=(
            str(item.get("last_failure_at"))
            if item.get("last_failure_at") else None
        ),
        evidence_refs=refs,
        source="RUNTIME_PREFLIGHT",
    )


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

    runtime_override = _runtime_health_override(record.capability_id)
    if runtime_override is not None:
        return runtime_override

    if str(record.health_policy or "") == "OPENCODE_REQUIRED":
        ph = provider_health("opencode")
        if ph.state in {
            "BLOCKED", "UPSTREAM_DENIED", "QUARANTINED", "AUTH_REQUIRED",
        }:
            return CapabilityHealth(
                capability_id=record.capability_id,
                state=(
                    QUARANTINED
                    if ph.state == "QUARANTINED"
                    else BLOCKED
                ),
                reason=ph.reason,
                retry_allowed=bool(ph.retry_allowed),
                confidence=0.98,
                sample_size=0,
                last_success_at=None,
                last_failure_at=None,
                evidence_refs=tuple(ph.evidence_refs),
                source="PROVIDER_HEALTH",
            )
        if ph.state == "AVAILABLE":
            return CapabilityHealth(
                capability_id=record.capability_id,
                state=HEALTHY,
                reason=ph.reason,
                retry_allowed=True,
                confidence=0.9,
                sample_size=0,
                last_success_at=None,
                last_failure_at=None,
                evidence_refs=tuple(ph.evidence_refs),
                source="PROVIDER_HEALTH",
            )

    if str(record.health_policy or "") == "SEMANTIC_PROVIDER_REQUIRED":
        semantic = semantic_provider_health()
        eligible = tuple(
            str(item)
            for item in (
                semantic.get("eligible_zero_cost_provider_ids") or ()
            )
            if str(item).strip()
        )
        provider_rows = [
            dict(item)
            for item in (semantic.get("providers") or ())
            if isinstance(item, dict)
        ]
        eligible_rows = [
            item
            for item in provider_rows
            if str(item.get("provider_id") or "") in eligible
        ]
        refs = tuple(dict.fromkeys(
            str(ref)
            for item in eligible_rows
            for ref in (item.get("evidence_refs") or ())
            if str(ref).strip()
        ))
        if bool(semantic.get("semantic_reasoning_available")) and eligible:
            return CapabilityHealth(
                capability_id=record.capability_id,
                state=HEALTHY,
                reason=(
                    "Harness-governed zero-cost semantic provider pool is "
                    "available: " + ",".join(sorted(eligible))
                ),
                retry_allowed=True,
                confidence=0.95,
                sample_size=len(eligible),
                last_success_at=None,
                last_failure_at=None,
                evidence_refs=refs,
                source="SEMANTIC_PROVIDER_HEALTH",
            )
        blocked_reasons = tuple(
            str(item.get("reason") or "").strip()
            for item in provider_rows
            if str(item.get("reason") or "").strip()
        )
        return CapabilityHealth(
            capability_id=record.capability_id,
            state=BLOCKED,
            reason=(
                "No Harness-governed zero-cost semantic provider is "
                "currently available."
                + (
                    " " + " | ".join(blocked_reasons[:3])
                    if blocked_reasons
                    else ""
                )
            )[:500],
            retry_allowed=any(
                bool(item.get("retry_allowed"))
                for item in provider_rows
            ),
            confidence=0.95,
            sample_size=len(provider_rows),
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=tuple(dict.fromkeys(
                str(ref)
                for item in provider_rows
                for ref in (item.get("evidence_refs") or ())
                if str(ref).strip()
            )),
            source="SEMANTIC_PROVIDER_HEALTH",
        )

    if str(record.health_policy or "") == "CODEX_AUTH_REQUIRED":
        github_actions = str(os.getenv("GITHUB_ACTIONS") or "").strip().lower()
        federation_config = str(
            os.getenv("BR_CODEX_FEDERATION_CONFIGURED") or ""
        ).strip().lower()
        if github_actions == "true" and federation_config == "false":
            return CapabilityHealth(
                capability_id=record.capability_id,
                state=BLOCKED,
                reason=(
                    "GitHub Actions runner cannot authorize Codex because the "
                    "repository federation rule/audience configuration is absent. "
                    "Harness must replan instead of selecting this capability."
                ),
                retry_allowed=False,
                confidence=1.0,
                sample_size=0,
                last_success_at=None,
                last_failure_at=None,
                evidence_refs=(
                    "runtime-config:OPENAI_FEDERATION_RULE_ID",
                    "runtime-config:OPENAI_FEDERATION_AUDIENCE",
                ),
                source="GITHUB_ACTIONS_CODEX_FEDERATION_CONFIG",
            )
        episodes = _episodes(record.capability_id)
        failure_memories = _failure_memories(record.capability_id)
        strongest_failure = max(
            failure_memories,
            key=lambda item: float(item.get("confidence") or 0.0),
            default=None,
        )
        refs = tuple(dict.fromkeys(
            str(ref)
            for item in [*episodes[:10], *failure_memories[:5]]
            for ref in (item.get("evidence_refs") or ())
            if str(ref)
        ))
        return CapabilityHealth(
            capability_id=record.capability_id,
            state=UNKNOWN,
            reason=(
                "Current Codex authentication must be proven on the executing "
                "runner immediately before this capability is treated as healthy."
            ),
            retry_allowed=False,
            confidence=max(
                0.5,
                float((strongest_failure or {}).get("confidence") or 0.0),
            ),
            sample_size=len(episodes),
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=refs,
            source="CODEX_AUTH_PREFLIGHT_REQUIRED",
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
