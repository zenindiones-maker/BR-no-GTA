from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import re
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


@dataclass(frozen=True)
class ModelHealth:
    provider_id: str
    model_id: str
    availability: str
    last_success: str | None
    last_failure: str | None
    failure_class: str | None
    latency_ms: float | None
    confidence: float
    sample_size: int
    rate_limit_state: str
    circuit_breaker_state: str
    evidence_refs: tuple[str, ...]

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
_RUNTIME_MODEL_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
)


def runtime_provider_binding(provider_id: str) -> dict[str, Any] | None:
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
    if (
        str(item.get("provider_id") or normalized)
        .strip()
        .lower()
        .replace("-", "_")
        != normalized
    ):
        return None
    if str(item.get("scope") or "").strip().upper() != "CURRENT_GITHUB_RUN":
        return None
    if str(item.get("github_run_id") or "").strip() != current_run_id:
        return None
    if str(item.get("state") or "").strip().upper() != "AVAILABLE":
        return None
    if not bool(item.get("zero_cost_eligible", False)):
        return None

    model_id = str(item.get("model_id") or "").strip()
    if not _RUNTIME_MODEL_ID_RE.fullmatch(model_id):
        return None

    proof = item.get("proof")
    if not isinstance(proof, dict):
        return None
    if any(
        str(proof.get(key) or "").strip().upper() != "PASS"
        for key in _RUNTIME_PROVIDER_PROOF_GATES
    ):
        return None
    if (
        str(proof.get("OPENAI_PLATFORM_API_KEY_REQUIRED") or "")
        .strip()
        .upper()
        != "NO"
    ):
        return None

    refs = tuple(
        str(ref).strip()
        for ref in (item.get("evidence_refs") or ())
        if str(ref).strip()
    )
    expected_prefix = f"github:run:{current_run_id}:"
    if not refs or not any(ref.startswith(expected_prefix) for ref in refs):
        return None

    return {
        "provider_id": normalized,
        "model_id": model_id,
        "github_run_id": current_run_id,
        "scope": "CURRENT_GITHUB_RUN",
        "zero_cost_eligible": True,
        "proof": {
            **{
                key: "PASS"
                for key in _RUNTIME_PROVIDER_PROOF_GATES
            },
            "OPENAI_PLATFORM_API_KEY_REQUIRED": "NO",
        },
        "evidence_refs": refs,
    }


def authorized_provider_model_binding(
    record: Any,
) -> dict[str, Any] | None:
    provider_id = str(getattr(record, "provider_id", None) or "").strip()
    if not provider_id:
        return None

    policy = str(
        getattr(record, "model_binding_policy", "STATIC_REGISTRY")
        or "STATIC_REGISTRY"
    ).strip().upper()
    static_model = str(getattr(record, "model_id", None) or "").strip()

    if policy == "STATIC_REGISTRY":
        if not static_model:
            return None
        return {
            "provider_id": provider_id.lower().replace("-", "_"),
            "model_id": static_model,
            "source": "REGISTRY_STATIC",
            "evidence_refs": (),
        }

    if policy != "CURRENT_RUN_RUNTIME_PROOF":
        return None

    runtime = runtime_provider_binding(provider_id)
    if runtime is None:
        return None
    runtime_model = str(runtime.get("model_id") or "").strip()
    if not runtime_model:
        return None
    if static_model and runtime_model != static_model:
        return None
    return {
        "provider_id": str(runtime["provider_id"]),
        "model_id": runtime_model,
        "source": "CURRENT_RUN_RUNTIME_PROOF",
        "evidence_refs": tuple(runtime.get("evidence_refs") or ()),
        "github_run_id": runtime.get("github_run_id"),
    }


def _runtime_provider_health_override(
    record: Any,
) -> ProviderHealth | None:
    binding = authorized_provider_model_binding(record)
    if (
        binding is None
        or binding.get("source") != "CURRENT_RUN_RUNTIME_PROOF"
    ):
        return None
    return ProviderHealth(
        provider_id=str(binding["provider_id"]),
        state="AVAILABLE",
        reason=(
            "Provider is Registry-available and live authenticated for the "
            "current GitHub execution only."
        ),
        evidence_refs=tuple(binding["evidence_refs"]),
        retry_allowed=True,
        zero_cost_eligible=True,
    )

def _runtime_model_health(provider_id: str, model_id: str) -> ModelHealth | None:
    raw=str(os.getenv("BR_RUNTIME_MODEL_HEALTH_JSON") or "").strip()
    if not raw: return None
    try: payload=json.loads(raw)
    except json.JSONDecodeError: return None
    provider=str(provider_id or "").strip().lower().replace("-","_")
    group=payload.get(provider) if isinstance(payload,dict) else None
    item=group.get(model_id) if isinstance(group,dict) else None
    if not isinstance(item,dict): return None
    circuit=str(item.get("circuit_breaker_state") or "CLOSED").upper()
    if circuit not in {"CLOSED","OPEN","HALF_OPEN"}: return None
    return ModelHealth(
        provider_id=provider,model_id=model_id,
        availability=str(item.get("availability") or "AVAILABLE").upper(),
        last_success=str(item.get("last_success") or "") or None,
        last_failure=str(item.get("last_failure") or "") or None,
        failure_class=str(item.get("failure_class") or "") or None,
        latency_ms=float(item["latency_ms"]) if isinstance(item.get("latency_ms"),(int,float)) else None,
        confidence=max(0.0,min(1.0,float(item.get("confidence") or 0.0))),
        sample_size=max(0,int(item.get("sample_size") or 0)),
        rate_limit_state=str(item.get("rate_limit_state") or "UNKNOWN").upper(),
        circuit_breaker_state=circuit,
        evidence_refs=tuple(str(x) for x in (item.get("evidence_refs") or ()) if str(x)))

def model_health(provider_id: str, model_id: str, *, registry: Any = GLOBAL_CAPABILITY_REGISTRY) -> ModelHealth:
    provider=str(provider_id or "").strip().lower().replace("-","_")
    model=str(model_id or "").strip()
    if not provider or not model: raise ValueError("provider_id and model_id are required")
    runtime=_runtime_model_health(provider,model)
    if runtime is not None: return runtime
    records=[r for r in registry.all()
             if r.capability_type=="PROVIDER"
             and str(r.provider_id or "").lower().replace("-","_")==provider
             and (
                 str(r.model_id or "")==model
                 or str((authorized_provider_model_binding(r) or {}).get("model_id") or "")==model
             )]
    if not records:
        return ModelHealth(provider,model,"BLOCKED",None,None,"not_registered",None,1.0,0,"UNKNOWN","OPEN",())
    record=records[0]
    failures=[]
    for item in _failure_rows():
        metadata=dict(item.get("metadata") or {})
        if item.get("capability_id")==record.capability_id or metadata.get("model_id")==model or model in str(item.get("claim") or ""):
            failures.append(item)
    latest=failures[0] if failures else None
    failure_class=str((latest or {}).get("failure_pattern") or "") or None
    refs=tuple(dict.fromkeys(str(ref) for item in failures[:5] for ref in (item.get("evidence_refs") or ()) if str(ref)))
    return ModelHealth(
        provider_id=provider,model_id=model,
        availability="DEGRADED" if failures else "AVAILABLE",
        last_success=None,last_failure=str((latest or {}).get("last_verified_at") or "") or None,
        failure_class=failure_class,latency_ms=None,
        confidence=float((latest or {}).get("confidence") or 0.0),
        sample_size=int((latest or {}).get("support_count") or 0),
        rate_limit_state="OBSERVED" if failure_class and "rate" in failure_class.casefold() else "UNKNOWN",
        circuit_breaker_state="CLOSED",evidence_refs=refs)

def provider_health(provider_id: str, *, registry: Any = GLOBAL_CAPABILITY_REGISTRY) -> ProviderHealth:
    provider = str(provider_id or "").strip().lower().replace("-", "_")
    if not provider:
        raise ValueError("provider_id is required")
    if provider == "ollama_local":
        return _local_openweight_health()

    failures = _failure_rows()
    if provider == "opencode" and registry is GLOBAL_CAPABILITY_REGISTRY:
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
        for record in registry.all()
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
    available_records=[record for record in records if record.available]
    assessments=[assess_zero_cost(record.cost_class,quota_available=True) for record in records]
    zero_cost_eligible=any(item.eligible for item in assessments)
    if not available_records:
        return ProviderHealth(
            provider_id=provider,state="DEGRADED",
            reason="No registered model/profile for this provider is AVAILABLE.",
            evidence_refs=(),retry_allowed=False,zero_cost_eligible=zero_cost_eligible)

    for record in available_records:
        runtime_override=_runtime_provider_health_override(record)
        if runtime_override is not None: return runtime_override
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
    auth_required=any(
        any(marker in str(requirement).upper() for marker in external_auth_markers)
        for record in available_records for requirement in record.requirements)
    runtime_auth_available=bool(
        provider=="nvidia_nim" and str(os.getenv("NVIDIA_API_KEY") or "").strip())
    state="AVAILABLE" if (not auth_required or runtime_auth_available) else "AUTH_REQUIRED"
    return ProviderHealth(
        provider_id=provider,state=state,
        reason=(
            "Provider runtime authentication is materialized inside the secret boundary."
            if runtime_auth_available else
            "Provider requires runtime authentication evidence."
            if auth_required else
            "Provider is Registry-available and has no active failure quarantine."),
        evidence_refs=(),retry_allowed=True,zero_cost_eligible=zero_cost_eligible)


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
