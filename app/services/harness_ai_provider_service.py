from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import time
from typing import Any, Callable

from app.services.ai_provider import AIProvider, AIProviderError
from app.services.ai_provider_factory import create_ai_provider
from app.services.global_capability_registry import (
    AVAILABLE,
    GLOBAL_CAPABILITY_REGISTRY,
)
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    resolve_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    normalize_provider_id,
    route_harness_request,
)
from app.services.nvidia_nim_provider import NvidiaNIMProvider
from app.services.opencode_executor_profile_service import (
    create_opencode_provider_for_active_profile,
)


HarnessAIProviderAuthorization = HarnessAuthorization


@dataclass(frozen=True)
class HarnessAIProviderEvidence:
    provider: str
    status: str
    active: bool
    authority: str
    authorized_action: str
    harness_decision_id: str
    execution_id: str
    authorization_id: str | None = None
    result: Any = None
    error: Any = None
    routing: dict[str, Any] | None = None
    model: str | None = None
    executor_binding: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    latency_seconds: float | None = None
    retry_count: int = 0
    evidence_refs: tuple[str, ...] = ()
    provider_profile_skill_id: str | None = None
    provider_profile_version: str | None = None
    provider_profile_content_ref: str | None = None
    provider_profile_checksum: str | None = None
    performance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error_message(exc: Exception) -> str:
    safe = str(getattr(exc, "safe_message", "") or str(exc) or type(exc).__name__)
    # Never persist credential-shaped values from provider transports.
    redactions = ("authorization", "api_key", "apikey", "token", "bearer")
    lowered = safe.lower()
    if any(term in lowered for term in redactions):
        return type(exc).__name__
    return safe[:1200]


def _execution_evidence_refs(
    *,
    decision: HarnessRoutingDecision,
    authorization: HarnessAuthorization,
    prompt: str,
) -> tuple[str, ...]:
    digest = sha256(prompt.encode("utf-8")).hexdigest()
    return (
        f"routing:{decision.routing_id}",
        f"authorization:{authorization.authorization_id}",
        f"execution:{authorization.execution_id}",
        f"prompt-sha256:{digest}",
    )


def _provider_record(provider_id: str):
    normalized = normalize_provider_id(provider_id)
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if (
            record.capability_type == "PROVIDER"
            and record.provider_id
            and normalize_provider_id(record.provider_id) == normalized
        ):
            return record
    return None


def _resolve_routing(
    *,
    provider_name: str | None,
    authorization: HarnessAIProviderAuthorization,
    routing_decision: HarnessRoutingDecision | None,
) -> tuple[HarnessRoutingDecision, HarnessAuthorization, str]:
    authorization = resolve_harness_authorization(authorization)

    if routing_decision is None:
        if not provider_name or not provider_name.strip():
            raise ValueError(
                "Harness AI provider selection requires a routing decision or provider name"
            )
        routing_decision = route_harness_request(
            HarnessRoutingRequest(
                intent="ai reasoning text provider selection",
                authorized_action=authorization.authorized_action,
                required_capability_id="ai.reasoning.text",
                provider_required=True,
                preferred_providers=(provider_name,),
                fallback_allowed=False,
            )
        )

    if routing_decision.authorized_action != authorization.authorized_action:
        raise PermissionError("Routing decision action does not match Harness authorization")
    if routing_decision.selected_capability_id != "ai.reasoning.text":
        raise PermissionError("AI provider selection requires ai.reasoning.text routing")
    if not routing_decision.selected_provider:
        raise PermissionError("Routing decision did not select an AI provider")
    if not routing_decision.selected_model:
        raise PermissionError(
            "Harness-governed AI provider execution requires an explicit selected model"
        )

    normalized_provider = normalize_provider_id(routing_decision.selected_provider)
    if provider_name and normalize_provider_id(provider_name) != normalized_provider:
        raise PermissionError("Requested provider does not match Harness routing decision")

    record = _provider_record(normalized_provider)
    if (
        record is None
        or record.availability != AVAILABLE
        or record.executor_binding is None
    ):
        raise ValueError(
            f"AI provider is not executable under Harness policy: {normalized_provider}"
        )
    if authorization.authorized_action not in record.allowed_actions:
        raise PermissionError(
            "AI provider is not authorized for action "
            f"{authorization.authorized_action!r}"
        )
    if routing_decision.selected_model != record.model_id:
        raise PermissionError("Routing decision model does not match Registry metadata")
    if routing_decision.selected_provider_executor_binding != record.executor_binding:
        raise PermissionError("Routing decision executor binding does not match Registry metadata")

    authorization = validate_harness_authorization(
        authorization,
        expected_action=routing_decision.authorized_action,
        expected_subject=f"provider:{normalized_provider}",
    )
    return routing_decision, authorization, normalized_provider


def select_harness_ai_provider(
    *,
    provider_name: str | None = None,
    authorization: HarnessAIProviderAuthorization,
    routing_decision: HarnessRoutingDecision | None = None,
) -> tuple[str, AIProvider]:
    """Construct exactly the AI provider selected by Harness routing/policy."""
    decision, resolved_authorization, normalized_provider = _resolve_routing(
        provider_name=provider_name,
        authorization=authorization,
        routing_decision=routing_decision,
    )

    if normalized_provider == "nvidia_nim":
        if "harness_ai_provider_service" not in (
            decision.selected_provider_executor_binding or ""
        ):
            raise PermissionError("NVIDIA executor escaped registered Harness binding")
        return normalized_provider, NvidiaNIMProvider(model=decision.selected_model)

    if normalized_provider == "tuxevil":
        if "ai_provider_factory.create_ai_provider" not in (
            decision.selected_provider_executor_binding or ""
        ):
            raise PermissionError("Tuxevil executor escaped registered Harness binding")
        return normalized_provider, create_ai_provider(
            model=decision.selected_model,
        )

    if normalized_provider == "opencode":
        if "opencode_executor_profile_service.create_opencode_provider_for_active_profile" not in (
            decision.selected_provider_executor_binding or ""
        ):
            raise PermissionError("OpenCode executor escaped governed profile resolver binding")
        return normalized_provider, create_opencode_provider_for_active_profile(
            routing_decision=decision,
            authorization=resolved_authorization,
        )

    raise ValueError(
        f"AI provider has no bounded Harness constructor: {normalized_provider}"
    )


def execute_harness_ai_generation(
    *,
    prompt: str,
    authorization: HarnessAIProviderAuthorization,
    provider_name: str | None = None,
    routing_decision: HarnessRoutingDecision | None = None,
    selector: Callable[..., tuple[str, AIProvider]] = select_harness_ai_provider,
) -> HarnessAIProviderEvidence:
    """Execute one routed provider and preserve structured observed evidence."""
    decision, resolved_authorization, expected_provider = _resolve_routing(
        provider_name=provider_name,
        authorization=authorization,
        routing_decision=routing_decision,
    )

    selector_provider_name = provider_name or expected_provider
    if selector is select_harness_ai_provider:
        normalized_provider, provider = selector(
            provider_name=selector_provider_name,
            authorization=resolved_authorization,
            routing_decision=decision,
        )
    else:
        normalized_provider, provider = selector(
            provider_name=selector_provider_name,
            authorization=resolved_authorization,
        )

    if normalize_provider_id(normalized_provider) != expected_provider:
        raise PermissionError("AI provider selector escaped Harness routing policy")

    started_at = _utcnow()
    started_perf = time.perf_counter()
    refs = _execution_evidence_refs(
        decision=decision,
        authorization=resolved_authorization,
        prompt=prompt,
    )
    executor_binding = (
        getattr(provider, "executor_binding", None)
        or decision.selected_provider_executor_binding
    )
    model = decision.selected_model
    profile = getattr(provider, "profile", None)
    profile_skill_id = profile.get("skill_id") if isinstance(profile, dict) else None
    profile_version = getattr(provider, "profile_version", None)
    profile_content_ref = getattr(provider, "profile_content_ref", None)
    profile_checksum = getattr(provider, "profile_checksum", None)

    try:
        response = provider.generate(prompt)
    except AIProviderError as exc:
        finished_at = _utcnow()
        latency = max(0.0, time.perf_counter() - started_perf)
        structured_error = (
            exc.to_dict()
            if callable(getattr(exc, "to_dict", None))
            else {
                "provider": expected_provider,
                "model": model,
                "code": "provider_error",
                "status_code": getattr(exc, "status_code", None),
                "retryable": bool(getattr(exc, "retryable", False)),
                "message": _safe_error_message(exc),
                "error_type": type(exc).__name__,
            }
        )
        return HarnessAIProviderEvidence(
            provider=expected_provider,
            status="FAILED",
            active=False,
            authority=resolved_authorization.authority,
            authorized_action=resolved_authorization.authorized_action,
            harness_decision_id=resolved_authorization.harness_decision_id,
            execution_id=resolved_authorization.execution_id,
            authorization_id=resolved_authorization.authorization_id,
            error=structured_error,
            routing=decision.to_dict(),
            model=model,
            executor_binding=executor_binding,
            started_at=started_at,
            finished_at=finished_at,
            latency_seconds=latency,
            retry_count=0,
            evidence_refs=refs,
            provider_profile_skill_id=profile_skill_id,
            provider_profile_version=profile_version,
            provider_profile_content_ref=profile_content_ref,
            provider_profile_checksum=profile_checksum,
            performance=dict(getattr(provider, "last_performance_metrics", {}) or {}),
        )
    except Exception as exc:
        finished_at = _utcnow()
        latency = max(0.0, time.perf_counter() - started_perf)
        return HarnessAIProviderEvidence(
            provider=expected_provider,
            status="FAILED",
            active=False,
            authority=resolved_authorization.authority,
            authorized_action=resolved_authorization.authorized_action,
            harness_decision_id=resolved_authorization.harness_decision_id,
            execution_id=resolved_authorization.execution_id,
            authorization_id=resolved_authorization.authorization_id,
            error={
                "provider": expected_provider,
                "model": model,
                "code": "provider_unexpected_error",
                "status_code": None,
                "retryable": False,
                "message": _safe_error_message(exc),
                "error_type": type(exc).__name__,
            },
            routing=decision.to_dict(),
            model=model,
            executor_binding=executor_binding,
            started_at=started_at,
            finished_at=finished_at,
            latency_seconds=latency,
            retry_count=0,
            evidence_refs=refs,
            provider_profile_skill_id=profile_skill_id,
            provider_profile_version=profile_version,
            provider_profile_content_ref=profile_content_ref,
            provider_profile_checksum=profile_checksum,
            performance=dict(getattr(provider, "last_performance_metrics", {}) or {}),
        )

    finished_at = _utcnow()
    latency = max(0.0, time.perf_counter() - started_perf)
    result = asdict(response)
    text = str(result.get("text") or "").strip()
    if not text:
        return HarnessAIProviderEvidence(
            provider=expected_provider,
            status="FAILED",
            active=False,
            authority=resolved_authorization.authority,
            authorized_action=resolved_authorization.authorized_action,
            harness_decision_id=resolved_authorization.harness_decision_id,
            execution_id=resolved_authorization.execution_id,
            result=result,
            error={
                "provider": expected_provider,
                "model": result.get("model") or model,
                "code": "empty_response",
                "status_code": None,
                "retryable": True,
                "message": "Provider returned no usable text response.",
                "error_type": "EmptyProviderResponse",
            },
            routing=decision.to_dict(),
            model=result.get("model") or model,
            executor_binding=executor_binding,
            started_at=started_at,
            finished_at=finished_at,
            latency_seconds=latency,
            retry_count=0,
            evidence_refs=refs,
            provider_profile_skill_id=profile_skill_id,
            provider_profile_version=profile_version,
            provider_profile_content_ref=profile_content_ref,
            provider_profile_checksum=profile_checksum,
            performance=dict(getattr(provider, "last_performance_metrics", {}) or {}),
        )

    return HarnessAIProviderEvidence(
        provider=expected_provider,
        status="EXECUTED",
        active=True,
        authority=resolved_authorization.authority,
        authorized_action=resolved_authorization.authorized_action,
        harness_decision_id=resolved_authorization.harness_decision_id,
        execution_id=resolved_authorization.execution_id,
        authorization_id=resolved_authorization.authorization_id,
        result=result,
        routing=decision.to_dict(),
        model=result.get("model") or model,
        executor_binding=executor_binding,
        started_at=started_at,
        finished_at=finished_at,
        latency_seconds=latency,
        retry_count=0,
        evidence_refs=refs,
        provider_profile_skill_id=profile_skill_id,
        provider_profile_version=profile_version,
        provider_profile_content_ref=profile_content_ref,
        provider_profile_checksum=profile_checksum,
    )
