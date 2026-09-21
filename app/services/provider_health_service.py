from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.zero_cost_policy_service import assess_zero_cost
from app.services.opencode_executor_profile_service import (
    SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    executable_opencode_executor_profile,
)


PROVIDER_HEALTH_STATES = {
    "AVAILABLE",
    "DEGRADED",
    "BLOCKED",
    "AUTH_REQUIRED",
    "UPSTREAM_DENIED",
    "QUARANTINED",
}


@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    state: str
    reason: str
    evidence_refs: tuple[str, ...]
    retry_allowed: bool
    zero_cost_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _failure_rows() -> list[dict[str, Any]]:
    try:
        return learning_repository.list_memories(
            status="ACTIVE",
            memory_type="FAILURE",
            limit=200,
        )
    except Exception:
        return []


def provider_health(provider_id: str) -> ProviderHealth:
    provider = str(provider_id or "").strip().lower().replace("-", "_")
    if not provider:
        raise ValueError("provider_id is required")

    failures = _failure_rows()
    if provider == "opencode":
        matching = [
            item for item in failures
            if item.get("failure_pattern") == "opencode_free_tier_403"
            or (
                "opencode" in str(item.get("claim") or "").casefold()
                and "403" in str(item.get("claim") or "").casefold()
            )
        ]
        if matching:
            refs = tuple(dict.fromkeys(
                str(ref)
                for item in matching
                for ref in (item.get("evidence_refs") or ())
                if str(ref)
            ))
            return ProviderHealth(
                provider_id="opencode",
                state="UPSTREAM_DENIED",
                reason="OpenCode free-tier admission is blocked upstream before inference.",
                evidence_refs=refs,
                retry_allowed=False,
                zero_cost_eligible=True,
            )

        semantic_profile = executable_opencode_executor_profile(
            SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION
        )
        semantic_options = dict(semantic_profile["options"])
        if (
            str(semantic_options.get("status") or "").startswith(
                "CANDIDATE_BLOCKED_UPSTREAM"
            )
            and not bool(semantic_options.get("usable_text_proof"))
        ):
            blocker_runs = tuple(
                int(run_id)
                for run_id in (semantic_options.get("runtime_blocker_runs") or ())
                if int(run_id) > 0
            )
            return ProviderHealth(
                provider_id="opencode",
                state="UPSTREAM_DENIED",
                reason=str(
                    semantic_options.get("runtime_blocker")
                    or "OpenCode semantic profile is blocked upstream before inference."
                ),
                evidence_refs=tuple(
                    f"github:run:{run_id}:opencode-semantic-v3-upstream-403"
                    for run_id in blocker_runs
                ),
                retry_allowed=False,
                zero_cost_eligible=True,
            )

    records = [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.capability_type == "PROVIDER"
        and str(record.provider_id or "").lower().replace("-", "_") == provider
    ]
    if not records:
        return ProviderHealth(
            provider_id=provider,
            state="BLOCKED",
            reason="No registered provider implementation.",
            evidence_refs=(),
            retry_allowed=False,
            zero_cost_eligible=False,
        )
    record = records[0]
    assessment = assess_zero_cost(record.cost_class, quota_available=True)
    if not record.available:
        return ProviderHealth(
            provider_id=provider,
            state="DEGRADED",
            reason=f"Registry availability is {record.availability}.",
            evidence_refs=(),
            retry_allowed=False,
            zero_cost_eligible=assessment.eligible,
        )
    external_auth_markers = (
        "API_KEY",
        "API KEY",
        "ACCESS_TOKEN",
        "AUTH_TOKEN",
        "BEARER_TOKEN",
        "OAUTH",
        "CREDENTIAL",
        "LOGIN_REQUIRED",
        "ACCOUNT_AUTH",
    )
    auth_required = any(
        any(marker in str(requirement).upper() for marker in external_auth_markers)
        for requirement in record.requirements
    )
    return ProviderHealth(
        provider_id=provider,
        state="AUTH_REQUIRED" if auth_required else "AVAILABLE",
        reason=(
            "Provider requires runtime authentication evidence."
            if auth_required
            else "Provider is Registry-available and has no active failure quarantine."
        ),
        evidence_refs=(),
        retry_allowed=True,
        zero_cost_eligible=assessment.eligible,
    )


def semantic_provider_health() -> dict[str, Any]:
    providers = [
        provider_health(provider)
        for provider in ("opencode", "tuxevil", "nvidia_nim", "gemini")
    ]
    zero_cost_ready = [
        item for item in providers
        if item.zero_cost_eligible
        and item.state == "AVAILABLE"
    ]
    return {
        "providers": [item.to_dict() for item in providers],
        "semantic_reasoning_available": bool(zero_cost_ready),
        "eligible_zero_cost_provider_ids": [
            item.provider_id for item in zero_cost_ready
        ],
        "opencode": provider_health("opencode").to_dict(),
    }
