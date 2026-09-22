from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from typing import Any
from urllib import request

from app.database import harness_learning_repository as learning_repository
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.zero_cost_policy_service import assess_zero_cost
from app.services.opencode_executor_profile_service import (
    SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    executable_opencode_executor_profile,
)
from app.services.local_openweight_ai_provider import (
    LOCAL_OPENWEIGHT_MODEL_DIGEST,
    LOCAL_OPENWEIGHT_MODEL_ID,
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


def _local_openweight_health() -> ProviderHealth:
    if os.getenv("BR_LOCAL_OPENWEIGHT_ENABLED", "").strip() != "1":
        return ProviderHealth(
            provider_id="ollama_local",
            state="BLOCKED",
            reason="Local open-weight runtime is not enabled in this process.",
            evidence_refs=("github:run:35658908009:zero-cost-proof",),
            retry_allowed=True,
            zero_cost_eligible=True,
        )
    url = os.getenv(
        "BR_LOCAL_OPENWEIGHT_URL",
        "http://127.0.0.1:11434",
    ).rstrip("/") + "/api/tags"
    try:
        with request.urlopen(url, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return ProviderHealth(
            provider_id="ollama_local",
            state="BLOCKED",
            reason=f"Local open-weight runtime readiness failed: {type(exc).__name__}",
            evidence_refs=("github:run:35658908009:zero-cost-proof",),
            retry_allowed=True,
            zero_cost_eligible=True,
        )
    rows = [
        item for item in (payload.get("models") or ())
        if isinstance(item, dict)
        and str(item.get("name") or item.get("model") or "") == LOCAL_OPENWEIGHT_MODEL_ID
    ]
    if len(rows) != 1:
        return ProviderHealth(
            provider_id="ollama_local",
            state="BLOCKED",
            reason="Proven local open-weight model is not loaded.",
            evidence_refs=("github:run:35658908009:zero-cost-proof",),
            retry_allowed=True,
            zero_cost_eligible=True,
        )
    digest = str(rows[0].get("digest") or "").removeprefix("sha256:")
    if digest != LOCAL_OPENWEIGHT_MODEL_DIGEST:
        return ProviderHealth(
            provider_id="ollama_local",
            state="QUARANTINED",
            reason="Local open-weight model digest does not match proven identity.",
            evidence_refs=("github:artifact:10665244270",),
            retry_allowed=False,
            zero_cost_eligible=False,
        )
    return ProviderHealth(
        provider_id="ollama_local",
        state="AVAILABLE",
        reason="Proven loopback-only Qwen3 runtime is ready with exact model digest.",
        evidence_refs=(
            "github:run:35658908009",
            "github:artifact:10665244270",
            f"model-digest:{LOCAL_OPENWEIGHT_MODEL_DIGEST}",
        ),
        retry_allowed=True,
        zero_cost_eligible=True,
    )


_RUNTIME_PROVIDER_PROOF_GATES = (
    "TUXEVIL_RESPONSES_API",
    "ANTIGRAVITY_UPSTREAM_AUTH",
    "TUXEVIL_LIVE_INFERENCE",
    "TUXEVIL_TOOL_CALLING",
)


def _runtime_provider_health_override(
    provider_id: str,
    *,
    zero_cost_eligible: bool,
) -> ProviderHealth | None:
    raw = str(os.getenv("BR_RUNTIME_PROVIDER_HEALTH_JSON") or "").strip()
    current_run_id = str(os.getenv("GITHUB_RUN_ID") or "").strip()
    if not raw or not current_run_id:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    normalized = str(provider_id or "").strip().lower().replace("-", "_")
    item = payload.get(normalized)
    if not isinstance(item, dict):
        return None
    if str(item.get("provider_id") or normalized).strip().lower().replace("-", "_") != normalized:
        return None
    if str(item.get("scope") or "").strip().upper() != "CURRENT_GITHUB_RUN":
        return None
    if str(item.get("github_run_id") or "").strip() != current_run_id:
        return None
    if str(item.get("state") or "").strip().upper() != "AVAILABLE":
        return None
    if not zero_cost_eligible or not bool(item.get("zero_cost_eligible", False)):
        return None

    proof = item.get("proof")
    if not isinstance(proof, dict):
        return None
    if any(str(proof.get(key) or "").strip().upper() != "PASS" for key in _RUNTIME_PROVIDER_PROOF_GATES):
        return None

    refs = tuple(
        str(ref).strip()
        for ref in (item.get("evidence_refs") or ())
        if str(ref).strip()
    )
    expected_prefix = f"github:run:{current_run_id}:"
    if not refs or not any(ref.startswith(expected_prefix) for ref in refs):
        return None

    return ProviderHealth(
        provider_id=normalized,
        state="AVAILABLE",
        reason=(
            "Provider is Registry-available and live authenticated for the "
            "current GitHub execution only."
        ),
        evidence_refs=refs,
        retry_allowed=True,
        zero_cost_eligible=True,
    )


def provider_health(provider_id: str) -> ProviderHealth:
    provider = str(provider_id or "").strip().lower().replace("-", "_")
    if not provider:
        raise ValueError("provider_id is required")
    if provider == "ollama_local":
        return _local_openweight_health()

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

    runtime_override = _runtime_provider_health_override(
        provider,
        zero_cost_eligible=assessment.eligible,
    )
    if runtime_override is not None:
        return runtime_override
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
        for provider in (
            "opencode", "ollama_local", "tuxevil", "nvidia_nim", "gemini"
        )
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
