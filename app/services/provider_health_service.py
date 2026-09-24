from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
import statistics
from pathlib import Path
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
    live_status: str | None = None
    http_status: int | None = None
    quota_state: str = "UNKNOWN"
    last_verified_at: str | None = None
    source: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_NVIDIA_CANONICAL_HEALTH_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "nvidia_runtime_health.json"
)
_DEFAULT_NVIDIA_HEALTH_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def _health_evidence_is_stale(
    last_verified_at: str | None,
    *,
    max_age_seconds: int | None = None,
) -> bool:
    value = str(last_verified_at or "").strip()
    if not value:
        return True
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    if max_age_seconds is None:
        raw = str(os.getenv("BR_NVIDIA_HEALTH_MAX_AGE_SECONDS") or "").strip()
        try:
            max_age_seconds = (
                int(raw)
                if raw
                else _DEFAULT_NVIDIA_HEALTH_MAX_AGE_SECONDS
            )
        except ValueError:
            max_age_seconds = _DEFAULT_NVIDIA_HEALTH_MAX_AGE_SECONDS
    if max_age_seconds <= 0:
        return True
    age = datetime.now(timezone.utc) - observed.astimezone(timezone.utc)
    return age.total_seconds() > max_age_seconds


def _canonical_nvidia_health_payload() -> dict[str, Any] | None:
    try:
        payload = json.loads(
            _NVIDIA_CANONICAL_HEALTH_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("provider_id") or "") != "nvidia_nim":
        return None
    if payload.get("free_endpoint_only") is not True:
        return None
    if str(payload.get("paid_api_billing") or "").upper() != "NO":
        return None
    if str(payload.get("paid_api_fallback") or "").upper() != "NO":
        return None
    if str(payload.get("unlimited") or "").upper() != "UNPROVEN":
        return None
    if not isinstance(payload.get("models"), dict):
        return None
    return payload


def _canonical_nvidia_model_health(model_id: str) -> ModelHealth | None:
    payload = _canonical_nvidia_health_payload()
    if payload is None:
        return None
    item = payload["models"].get(model_id)
    if not isinstance(item, dict):
        return None
    evidence_ref = str(item.get("evidence_ref") or "").strip()
    run_id = str(payload.get("canonical_run_id") or "").strip()
    if not run_id.isdigit() or not evidence_ref.startswith(
        f"github:run:{run_id}:nvidia-model:"
    ):
        return None
    last_verified_at = str(
        item.get("last_verified_at")
        or payload.get("last_verified_at")
        or ""
    ).strip() or None
    max_age = payload.get("stale_after_seconds")
    max_age_seconds = int(max_age) if isinstance(max_age, int) else None
    stale = _health_evidence_is_stale(
        last_verified_at,
        max_age_seconds=max_age_seconds,
    )
    health = str(item.get("health") or "UNKNOWN/UNPROVEN").upper()
    live_status = str(item.get("live_status") or "").upper() or None
    failure_class = str(item.get("failure_class") or "").strip() or None
    if stale:
        health = "UNKNOWN/UNPROVEN"
        live_status = "STALE"
        failure_class = "stale_live_health_evidence"
    latency = item.get("latency_ms")
    http_status = item.get("http_status")
    return ModelHealth(
        provider_id="nvidia_nim",
        model_id=model_id,
        availability=health,
        last_success=last_verified_at if health == "AVAILABLE" else None,
        last_failure=last_verified_at if health != "AVAILABLE" else None,
        failure_class=failure_class,
        latency_ms=(
            float(latency)
            if isinstance(latency, (int, float))
            else None
        ),
        confidence=1.0,
        sample_size=1,
        rate_limit_state=str(
            item.get("rate_limit_state") or "UNKNOWN"
        ).upper(),
        circuit_breaker_state=str(
            item.get("circuit_breaker_state") or "CLOSED"
        ).upper(),
        evidence_refs=(evidence_ref,),
        live_status=live_status,
        http_status=(
            int(http_status)
            if isinstance(http_status, int)
            and not isinstance(http_status, bool)
            else None
        ),
        quota_state=str(item.get("quota_state") or "UNKNOWN").upper(),
        last_verified_at=last_verified_at,
        source="CANONICAL_LIVE_EVIDENCE",
    )


def _linear_percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(percentile)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def nvidia_semantic_planner_latency_budget(
    *,
    registry: Any = GLOBAL_CAPABILITY_REGISTRY,
) -> dict[str, Any]:
    """Derive bounded semantic-planner latency policy from canonical live health.

    Only NVIDIA models that are currently AVAILABLE and satisfy the semantic
    planning quality contract contribute samples. The model attempt deadline is
    the observed sane maximum rounded up to the next whole second; it is not a
    hand-tuned timeout. One fast transient retry may consume only the remaining
    time inside that same model-attempt budget. Full timeout/read-stall failures
    never receive a same-model retry.
    """
    required = {"semantic_planning", "reasoning", "structured_output"}
    samples: list[dict[str, Any]] = []
    for record in registry.all():
        if (
            record.capability_type != "PROVIDER"
            or str(record.provider_id or "").lower().replace("-", "_")
            != "nvidia_nim"
        ):
            continue
        model_id = str(getattr(record, "model_id", None) or "").strip()
        if not model_id:
            continue
        capabilities = {
            str(tag).split(":", 1)[1]
            for tag in tuple(getattr(record, "policy_tags", ()) or ())
            if str(tag).startswith("model-capability:")
        }
        if not required.issubset(capabilities):
            continue
        health = model_health("nvidia_nim", model_id, registry=registry)
        if health.availability != "AVAILABLE" or health.latency_ms is None:
            continue
        latency_ms = float(health.latency_ms)
        if latency_ms <= 0:
            continue
        samples.append({
            "model_id": model_id,
            "latency_ms": latency_ms,
            "evidence_refs": list(health.evidence_refs),
            "source": health.source,
        })
    if not samples:
        raise RuntimeError("NVIDIA_SEMANTIC_LATENCY_EVIDENCE_UNAVAILABLE")

    latencies = [float(item["latency_ms"]) for item in samples]
    p50_ms = float(statistics.median(latencies))
    p95_ms = float(_linear_percentile(latencies, 0.95))
    sane_max_ms = float(max(latencies))
    attempt_deadline_ms = int(math.ceil(sane_max_ms / 1000.0) * 1000)
    failover_budget = min(1, max(0, len(samples) - 1))
    total_deadline_ms = attempt_deadline_ms * (1 + failover_budget)
    return {
        "schema": "nvidia-semantic-latency-budget/v1",
        "sample_count": len(samples),
        "samples": samples,
        "P50_MS": round(p50_ms, 3),
        "P95_MS": round(p95_ms, 3),
        "MAX_SANE_MS": round(sane_max_ms, 3),
        "MODEL_ATTEMPT_DEADLINE_MS": attempt_deadline_ms,
        "MODEL_RETRY_BUDGET": 1,
        "FULL_TIMEOUT_RETRY_BUDGET": 0,
        "MODEL_FAILOVER_BUDGET": failover_budget,
        "SEMANTIC_PLANNER_TOTAL_DEADLINE_MS": total_deadline_ms,
        "derivation": (
            "attempt=ceil(max AVAILABLE semantic-capable live latency); "
            "total=attempt*(1+bounded failover)"
        ),
    }


def _learning_nvidia_model_health(
    record: Any,
    model_id: str,
) -> ModelHealth | None:
    try:
        episodes = learning_repository.list_episodes(
            domain="ai",
            capability_id=str(record.capability_id),
            limit=25,
        )
    except Exception:
        return None
    for episode in episodes:
        if (
            str(episode.get("provider") or "")
            .strip()
            .lower()
            .replace("-", "_")
            != "nvidia_nim"
        ):
            continue
        run_ref = str(episode.get("run_ref") or "").strip()
        if re.fullmatch(r"github:run:\d+", run_ref) is None:
            continue
        outcome = episode.get("actual_outcome")
        if not isinstance(outcome, dict):
            continue
        if str(outcome.get("MODEL_ID") or "") != model_id:
            continue
        if (
            str(outcome.get("BILLING_CLASS") or "").upper()
            != "NVIDIA_FREE_ENDPOINT"
        ):
            continue
        if str(outcome.get("PAID_API_BILLING") or "NO").upper() != "NO":
            continue
        last_verified_at = str(
            episode.get("finished_at")
            or episode.get("created_at")
            or ""
        ).strip() or None
        refs = tuple(dict.fromkeys(
            [
                *[
                    str(ref)
                    for ref in (episode.get("evidence_refs") or ())
                    if str(ref)
                ],
                str(outcome.get("EVIDENCE_REF") or ""),
            ]
        ))
        refs = tuple(ref for ref in refs if ref)
        run_id = run_ref.rsplit(":", 1)[-1]
        if not refs or not any(
            ref.startswith(f"github:run:{run_id}:nvidia-model:")
            for ref in refs
        ):
            continue
        stale = _health_evidence_is_stale(last_verified_at)
        health = str(
            outcome.get("HEALTH") or "UNKNOWN/UNPROVEN"
        ).upper()
        failure_class = (
            str(outcome.get("FAILURE_CLASS") or "").strip() or None
        )
        live_status = (
            "PASS"
            if health == "AVAILABLE"
            and outcome.get("RESPONSE_VALID") is True
            else "FAIL"
        )
        if stale:
            health = "UNKNOWN/UNPROVEN"
            live_status = "STALE"
            failure_class = "stale_live_health_evidence"
        latency = outcome.get("LATENCY_MS")
        http_status = outcome.get("HTTP_STATUS")
        return ModelHealth(
            provider_id="nvidia_nim",
            model_id=model_id,
            availability=health,
            last_success=(
                last_verified_at if health == "AVAILABLE" else None
            ),
            last_failure=(
                last_verified_at if health != "AVAILABLE" else None
            ),
            failure_class=failure_class,
            latency_ms=(
                float(latency)
                if isinstance(latency, (int, float))
                else None
            ),
            confidence=1.0,
            sample_size=1,
            rate_limit_state=(
                "OBSERVED"
                if outcome.get("RATE_LIMIT_OBSERVED") is True
                else "CLEAR"
            ),
            circuit_breaker_state="CLOSED",
            evidence_refs=refs,
            live_status=live_status,
            http_status=(
                int(http_status)
                if isinstance(http_status, int)
                and not isinstance(http_status, bool)
                else None
            ),
            quota_state="AVAILABLE_UNMEASURED",
            last_verified_at=last_verified_at,
            source="LEARNING_PLANE_LIVE_EVIDENCE",
        )
    return None


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

def _runtime_model_health(
    provider_id: str,
    model_id: str,
) -> ModelHealth | None:
    raw = str(os.getenv("BR_RUNTIME_MODEL_HEALTH_JSON") or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    provider = str(provider_id or "").strip().lower().replace("-", "_")
    group = payload.get(provider) if isinstance(payload, dict) else None
    item = group.get(model_id) if isinstance(group, dict) else None
    if not isinstance(item, dict):
        return None
    current_run_id = str(os.getenv("GITHUB_RUN_ID") or "").strip()
    evidence_run_id = str(item.get("github_run_id") or "").strip()
    refs = tuple(
        str(value)
        for value in (item.get("evidence_refs") or ())
        if str(value)
    )
    if current_run_id:
        expected_prefix = f"github:run:{current_run_id}:"
        if evidence_run_id != current_run_id:
            return None
        if not refs or not any(
            ref.startswith(expected_prefix) for ref in refs
        ):
            return None
    circuit = str(
        item.get("circuit_breaker_state") or "CLOSED"
    ).upper()
    if circuit not in {"CLOSED", "OPEN", "HALF_OPEN"}:
        return None
    availability = str(
        item.get("availability") or "AVAILABLE"
    ).upper()
    last_verified_at = str(
        item.get("last_verified_at")
        or item.get("last_success")
        or item.get("last_failure")
        or ""
    ).strip() or None
    http_status = item.get("http_status")
    return ModelHealth(
        provider_id=provider,
        model_id=model_id,
        availability=availability,
        last_success=str(item.get("last_success") or "") or None,
        last_failure=str(item.get("last_failure") or "") or None,
        failure_class=(
            str(item.get("failure_class") or "").strip() or None
        ),
        latency_ms=(
            float(item["latency_ms"])
            if isinstance(item.get("latency_ms"), (int, float))
            else None
        ),
        confidence=max(
            0.0,
            min(1.0, float(item.get("confidence") or 0.0)),
        ),
        sample_size=max(0, int(item.get("sample_size") or 0)),
        rate_limit_state=str(
            item.get("rate_limit_state") or "UNKNOWN"
        ).upper(),
        circuit_breaker_state=circuit,
        evidence_refs=refs,
        live_status=str(
            item.get("live_status")
            or ("PASS" if availability == "AVAILABLE" else "FAIL")
        ).upper(),
        http_status=(
            int(http_status)
            if isinstance(http_status, int)
            and not isinstance(http_status, bool)
            else None
        ),
        quota_state=str(
            item.get("quota_state") or "UNKNOWN"
        ).upper(),
        last_verified_at=last_verified_at,
        source="CURRENT_RUN_RUNTIME_PROOF",
    )


def model_health(
    provider_id: str,
    model_id: str,
    *,
    registry: Any = GLOBAL_CAPABILITY_REGISTRY,
) -> ModelHealth:
    provider = str(provider_id or "").strip().lower().replace("-", "_")
    model = str(model_id or "").strip()
    if not provider or not model:
        raise ValueError("provider_id and model_id are required")

    runtime = _runtime_model_health(provider, model)
    if runtime is not None:
        return runtime

    records = [
        record
        for record in registry.all()
        if record.capability_type == "PROVIDER"
        and str(record.provider_id or "").lower().replace("-", "_")
        == provider
        and (
            str(record.model_id or "") == model
            or str(
                (
                    authorized_provider_model_binding(record)
                    or {}
                ).get("model_id")
                or ""
            )
            == model
        )
    ]
    if not records:
        return ModelHealth(
            provider,
            model,
            "BLOCKED",
            None,
            None,
            "not_registered",
            None,
            1.0,
            0,
            "UNKNOWN",
            "OPEN",
            (),
        )

    record = records[0]
    if (
        str(getattr(record, "health_policy", "") or "").upper()
        == "PROVIDER_AND_MODEL_RUNTIME_HEALTH"
    ):
        if provider == "nvidia_nim":
            persisted = _learning_nvidia_model_health(record, model)
            if persisted is None:
                persisted = _canonical_nvidia_model_health(model)
            if persisted is not None:
                return persisted
        return ModelHealth(
            provider_id=provider,
            model_id=model,
            availability="UNKNOWN/UNPROVEN",
            last_success=None,
            last_failure=None,
            failure_class="live_runtime_proof_required",
            latency_ms=None,
            confidence=0.0,
            sample_size=0,
            rate_limit_state="UNKNOWN",
            circuit_breaker_state="CLOSED",
            evidence_refs=(),
            live_status="UNPROVEN",
            quota_state="UNKNOWN",
            source="NO_LIVE_EVIDENCE",
        )

    failures = []
    for item in _failure_rows():
        metadata = dict(item.get("metadata") or {})
        if (
            item.get("capability_id") == record.capability_id
            or metadata.get("model_id") == model
            or model in str(item.get("claim") or "")
        ):
            failures.append(item)
    latest = failures[0] if failures else None
    failure_class = (
        str((latest or {}).get("failure_pattern") or "") or None
    )
    refs = tuple(dict.fromkeys(
        str(ref)
        for item in failures[:5]
        for ref in (item.get("evidence_refs") or ())
        if str(ref)
    ))
    return ModelHealth(
        provider_id=provider,
        model_id=model,
        availability="DEGRADED" if failures else "AVAILABLE",
        last_success=None,
        last_failure=(
            str((latest or {}).get("last_verified_at") or "") or None
        ),
        failure_class=failure_class,
        latency_ms=None,
        confidence=float((latest or {}).get("confidence") or 0.0),
        sample_size=int((latest or {}).get("support_count") or 0),
        rate_limit_state=(
            "OBSERVED"
            if failure_class and "rate" in failure_class.casefold()
            else "UNKNOWN"
        ),
        circuit_breaker_state="CLOSED",
        evidence_refs=refs,
        last_verified_at=(
            str((latest or {}).get("last_verified_at") or "") or None
        ),
        source=(
            "FAILURE_MEMORY" if failures else "REGISTRY_DEFAULT"
        ),
    )

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

    if provider == "nvidia_nim":
        live_models: list[str] = []
        live_refs: list[str] = []
        observed_models: list[ModelHealth] = []
        for record in available_records:
            model_id = str(
                getattr(record, "model_id", None) or ""
            ).strip()
            if not model_id:
                continue
            observed = model_health(
                provider,
                model_id,
                registry=registry,
            )
            observed_models.append(observed)
            live_refs.extend(observed.evidence_refs)
            if observed.availability == "AVAILABLE":
                live_models.append(model_id)

        runtime_auth_available = bool(
            str(os.getenv("NVIDIA_API_KEY") or "").strip()
        )
        if live_models and not runtime_auth_available:
            return ProviderHealth(
                provider_id=provider,
                state="AUTH_REQUIRED",
                reason="Provider requires runtime authentication evidence.",
                evidence_refs=tuple(dict.fromkeys(live_refs)),
                retry_allowed=True,
                zero_cost_eligible=zero_cost_eligible,
            )
        if live_models:
            sources = sorted({
                item.source
                for item in observed_models
                if item.availability == "AVAILABLE"
            })
            return ProviderHealth(
                provider_id=provider,
                state="AVAILABLE",
                reason=(
                    f"{len(live_models)} NVIDIA NIM model(s) have "
                    "non-stale live health evidence and the existing "
                    "NVIDIA_API_KEY is materialized; "
                    f"sources={','.join(sources)}."
                ),
                evidence_refs=tuple(dict.fromkeys(live_refs)),
                retry_allowed=True,
                zero_cost_eligible=zero_cost_eligible,
            )
        if runtime_auth_available:
            return ProviderHealth(
                provider_id=provider,
                state="DEGRADED",
                reason=(
                    "NVIDIA_API_KEY is materialized, but no registered "
                    "NVIDIA model currently has non-stale AVAILABLE "
                    "live evidence."
                ),
                evidence_refs=tuple(dict.fromkeys(live_refs)),
                retry_allowed=True,
                zero_cost_eligible=zero_cost_eligible,
            )

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


def revalidate_nvidia_model_runtime_health(
    model_id: str,
    *,
    timeout_seconds: float,
    registry: Any = GLOBAL_CAPABILITY_REGISTRY,
) -> dict[str, Any]:
    """Bounded current-run health revalidation for one Harness-selected model.

    DEGRADED/UNKNOWN evidence remains ineligible for normal routing. This
    performs exactly one live probe and writes a CURRENT_RUN_RUNTIME_PROOF
    override only when that probe succeeds.
    """
    model = str(model_id or "").strip()
    if not model:
        raise ValueError("model_id is required")
    timeout = float(timeout_seconds)
    if timeout <= 0:
        raise ValueError("timeout_seconds must be positive")
    record = next(
        (
            item
            for item in registry.all()
            if item.capability_type == "PROVIDER"
            and str(item.provider_id or "").lower().replace("-", "_")
            == "nvidia_nim"
            and str(getattr(item, "model_id", None) or "") == model
        ),
        None,
    )
    if record is None or not record.available:
        raise ValueError("NVIDIA recovery model is not Registry-available")
    if str(record.cost_class or "").upper() != "FREE_ENDPOINT":
        raise PermissionError(
            "NVIDIA recovery health probe must remain zero-cost"
        )

    from app.services.nvidia_nim_provider import NvidiaNimProviderAdapter

    started_at = datetime.now(timezone.utc)
    provider = NvidiaNimProviderAdapter(
        model=model,
        max_retries=0,
        timeout_seconds=timeout,
    )
    error_payload: dict[str, Any] | None = None
    try:
        probe = provider.probe_capabilities()
    except Exception as exc:
        safe = (
            exc.to_dict()
            if callable(getattr(exc, "to_dict", None))
            else {
                "code": type(exc).__name__,
                "status_code": None,
                "retryable": False,
            }
        )
        error_payload = dict(safe or {})
        probe = {
            "MODEL_ID": model,
            "HTTP_STATUS": error_payload.get("status_code"),
            "RESPONSE_VALID": False,
            "LATENCY_MS": round(
                max(
                    0.0,
                    float(
                        provider.last_performance_metrics.get(
                            "latency_seconds"
                        )
                        or (
                            datetime.now(timezone.utc) - started_at
                        ).total_seconds()
                    ),
                )
                * 1000.0,
                3,
            ),
            "TOOL_USE_SUPPORTED": False,
            "STRUCTURED_OUTPUT_RESULT": "FAIL",
            "RATE_LIMIT_OBSERVED": (
                error_payload.get("code") == "rate_limited"
            ),
            "HEALTH": "DEGRADED",
            "FAILURE_CLASS": (
                error_payload.get("code") or type(exc).__name__
            ),
        }

    finished_at = datetime.now(timezone.utc)
    response_valid = probe.get("RESPONSE_VALID") is True
    structured_valid = (
        str(probe.get("STRUCTURED_OUTPUT_RESULT") or "").upper()
        == "PASS"
    )
    available = bool(response_valid and structured_valid)
    run_id = str(os.getenv("GITHUB_RUN_ID") or "local").strip() or "local"
    model_hash = sha256(model.encode("utf-8")).hexdigest()[:16]
    evidence_ref = (
        f"github:run:{run_id}:nvidia-model-revalidation:{model_hash}"
    )
    latency_ms = float(probe.get("LATENCY_MS") or 0.0)
    item = {
        "availability": "AVAILABLE" if available else "DEGRADED",
        "last_success": finished_at.isoformat() if available else None,
        "last_failure": None if available else finished_at.isoformat(),
        "failure_class": (
            None
            if available
            else str(
                probe.get("FAILURE_CLASS")
                or (error_payload or {}).get("code")
                or "health_revalidation_failed"
            )
        ),
        "latency_ms": latency_ms if latency_ms > 0 else None,
        "confidence": 1.0,
        "sample_size": 1,
        "rate_limit_state": (
            "RATE_LIMITED"
            if probe.get("RATE_LIMIT_OBSERVED") is True
            else "CLEAR"
        ),
        "circuit_breaker_state": "CLOSED",
        "github_run_id": run_id,
        "evidence_refs": [evidence_ref],
        "live_status": "PASS" if available else "FAIL",
        "http_status": probe.get("HTTP_STATUS"),
        "quota_state": "AVAILABLE_UNMEASURED",
        "last_verified_at": finished_at.isoformat(),
    }

    raw = str(os.getenv("BR_RUNTIME_MODEL_HEALTH_JSON") or "").strip()
    try:
        runtime_payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        runtime_payload = {}
    if not isinstance(runtime_payload, dict):
        runtime_payload = {}
    group = runtime_payload.setdefault("nvidia_nim", {})
    if not isinstance(group, dict):
        group = {}
        runtime_payload["nvidia_nim"] = group
    group[model] = item
    os.environ["BR_RUNTIME_MODEL_HEALTH_JSON"] = json.dumps(
        runtime_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )

    return {
        "schema": "NvidiaModelHealthRevalidation/v1",
        "provider_id": "nvidia_nim",
        "model_id": model,
        "availability": item["availability"],
        "health_probe_passed": available,
        "structured_output_probe_passed": structured_valid,
        "response_valid": response_valid,
        "latency_ms": item["latency_ms"],
        "http_status": item["http_status"],
        "failure_class": item["failure_class"],
        "evidence_refs": [evidence_ref],
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "timeout_seconds": timeout,
    }


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
