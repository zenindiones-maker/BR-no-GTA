from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from app.services.global_capability_registry import (
    AVAILABLE,
    FUNCTIONAL,
    GLOBAL_CAPABILITY_REGISTRY,
    PARTIAL,
    PROVEN,
    CapabilityRecord,
    GlobalCapabilityRegistry,
)


_MATURITY_RANK = {
    PROVEN: 0,
    FUNCTIONAL: 1,
    PARTIAL: 2,
}
_PROVIDER_ALIASES = {
    "nvidia": "nvidia_nim",
    "nim": "nvidia_nim",
    "nvidia_nim": "nvidia_nim",
    "tuxevil": "tuxevil",
    "gemini": "gemini",
    "higgsfield": "higgsfield",
}


class RoutingPolicyError(RuntimeError):
    """Fail-closed Harness routing rejection with audit-safe metadata."""

    def __init__(self, message: str, *, evidence: dict[str, Any] | None = None):
        super().__init__(message)
        self.evidence = dict(evidence or {})


@dataclass(frozen=True)
class HarnessRoutingRequest:
    intent: str
    authorized_action: str
    domain: str | None = None
    required_capability_id: str | None = None
    required_policy_tags: tuple[str, ...] = ()
    required_security_terms: tuple[str, ...] = ()
    provider_required: bool = False
    provider_domain: str = "ai"
    preferred_providers: tuple[str, ...] = ()
    allowed_providers: tuple[str, ...] = ()
    preferred_models: tuple[str, ...] = ()
    unavailable_provider_ids: tuple[str, ...] = ()
    quality_requirement: str | None = None
    latency_constraint: str | None = None
    cost_constraint: str | None = None
    quota_constraint: str | None = None
    fallback_allowed: bool = False


@dataclass(frozen=True)
class RoutingRejection:
    candidate_id: str
    stage: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class HarnessRoutingDecision:
    routing_id: str
    intent: str
    authorized_action: str
    candidate_capability_ids: tuple[str, ...]
    selected_capability_id: str
    selected_provider: str | None
    selected_model: str | None
    selected_executor_binding: str
    selected_provider_executor_binding: str | None
    primary_provider: str | None
    fallback_allowed: bool
    fallback_candidates: tuple[str, ...]
    fallback_occurred: bool
    evidence_expectations: tuple[str, ...]
    rationale: tuple[str, ...]
    rejected_candidates: tuple[RoutingRejection, ...]
    policy_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_provider_id(provider_id: str) -> str:
    normalized = provider_id.strip().lower().replace("-", "_")
    return _PROVIDER_ALIASES.get(normalized, normalized)


def _record_matches_security(
    record: CapabilityRecord,
    request: HarnessRoutingRequest,
) -> bool:
    if not request.required_security_terms:
        return True
    haystack = " ".join(
        (
            record.security_boundary,
            *record.policy_tags,
        )
    ).lower()
    return all(term.lower() in haystack for term in request.required_security_terms)


def _constraint_reasons(
    record: CapabilityRecord,
    request: HarnessRoutingRequest,
) -> list[str]:
    reasons: list[str] = []
    if record.availability != AVAILABLE:
        reasons.append(f"availability={record.availability}")
    if request.authorized_action not in record.allowed_actions:
        reasons.append("authorized_action_not_allowed")
    if request.domain and record.domain != request.domain:
        reasons.append(f"domain_mismatch:{record.domain}")
    if request.required_policy_tags and not set(request.required_policy_tags).issubset(
        set(record.policy_tags)
    ):
        reasons.append("required_policy_tags_missing")
    if not _record_matches_security(record, request):
        reasons.append("security_boundary_mismatch")
    if request.quality_requirement and record.quality_class != request.quality_requirement:
        reasons.append(f"quality_mismatch:{record.quality_class}")
    if request.latency_constraint and record.latency_class != request.latency_constraint:
        reasons.append(f"latency_mismatch:{record.latency_class}")
    if request.cost_constraint and record.cost_class != request.cost_constraint:
        reasons.append(f"cost_mismatch:{record.cost_class}")
    if request.quota_constraint and record.quota_class != request.quota_constraint:
        reasons.append(f"quota_mismatch:{record.quota_class}")
    if record.executor_binding is None:
        reasons.append("missing_executor_binding")
    return reasons


def _capability_candidates(
    request: HarnessRoutingRequest,
    registry: GlobalCapabilityRegistry,
) -> tuple[list[CapabilityRecord], list[RoutingRejection], tuple[str, ...]]:
    discovered = registry.discover(
        intent=request.intent,
        authorized_action=request.authorized_action,
        limit=max(50, len(registry.all())),
    )
    discovered_ids = [
        item["capability_id"]
        for item in discovered
        if isinstance(item.get("capability_id"), str)
    ]

    if request.required_capability_id and request.required_capability_id not in discovered_ids:
        discovered_ids.insert(0, request.required_capability_id)

    candidates: list[CapabilityRecord] = []
    rejected: list[RoutingRejection] = []
    seen: set[str] = set()

    for capability_id in discovered_ids:
        if capability_id in seen:
            continue
        seen.add(capability_id)
        record = registry.get(capability_id)
        if record is None:
            rejected.append(
                RoutingRejection(capability_id, "capability", ("not_registered",))
            )
            continue
        if record.capability_type == "PROVIDER":
            continue
        if request.required_capability_id and record.capability_id != request.required_capability_id:
            continue
        reasons = _constraint_reasons(record, request)
        if reasons:
            rejected.append(
                RoutingRejection(record.capability_id, "capability", tuple(reasons))
            )
            continue
        candidates.append(record)

    return candidates, rejected, tuple(discovered_ids)


def _provider_records(
    request: HarnessRoutingRequest,
    registry: GlobalCapabilityRegistry,
) -> tuple[list[CapabilityRecord], list[RoutingRejection]]:
    allowed = {
        normalize_provider_id(provider_id)
        for provider_id in request.allowed_providers
    }
    unavailable = {
        normalize_provider_id(provider_id)
        for provider_id in request.unavailable_provider_ids
    }

    eligible: list[CapabilityRecord] = []
    rejected: list[RoutingRejection] = []
    for record in registry.all():
        if record.capability_type != "PROVIDER" or not record.provider_id:
            continue
        if record.domain != request.provider_domain:
            continue
        provider_id = normalize_provider_id(record.provider_id)
        reasons: list[str] = []
        if record.availability != AVAILABLE:
            reasons.append(f"availability={record.availability}")
        if request.authorized_action not in record.allowed_actions:
            reasons.append("authorized_action_not_allowed")
        if record.executor_binding is None:
            reasons.append("missing_executor_binding")
        if allowed and provider_id not in allowed:
            reasons.append("provider_not_allowed_by_request")
        if provider_id in unavailable:
            reasons.append("provider_runtime_unavailable")
        if request.preferred_models and record.model_id not in request.preferred_models:
            reasons.append("model_not_allowed_by_request")
        if not _record_matches_security(record, request):
            reasons.append("security_boundary_mismatch")

        if reasons:
            rejected.append(
                RoutingRejection(record.capability_id, "provider", tuple(reasons))
            )
            continue
        eligible.append(record)

    preference_order = {
        normalize_provider_id(provider_id): index
        for index, provider_id in enumerate(request.preferred_providers)
    }
    eligible.sort(
        key=lambda record: (
            preference_order.get(
                normalize_provider_id(record.provider_id or ""),
                len(preference_order) + 1,
            ),
            _MATURITY_RANK.get(record.maturity, 99),
            record.capability_id,
        )
    )
    return eligible, rejected


def _select_provider(
    request: HarnessRoutingRequest,
    registry: GlobalCapabilityRegistry,
) -> tuple[
    CapabilityRecord | None,
    str | None,
    tuple[str, ...],
    bool,
    list[RoutingRejection],
]:
    if not request.provider_required:
        return None, None, (), False, []

    eligible, rejected = _provider_records(request, registry)
    preferred = tuple(normalize_provider_id(item) for item in request.preferred_providers)
    primary_provider = preferred[0] if preferred else (
        normalize_provider_id(eligible[0].provider_id or "") if eligible else None
    )

    by_provider = {
        normalize_provider_id(record.provider_id or ""): record
        for record in eligible
    }
    primary = by_provider.get(primary_provider or "")
    if primary is not None:
        fallback_candidates = tuple(
            normalize_provider_id(record.provider_id or "")
            for record in eligible
            if record is not primary and record.fallback_eligibility
        ) if request.fallback_allowed else ()
        return primary, primary_provider, fallback_candidates, False, rejected

    if not request.fallback_allowed:
        raise RoutingPolicyError(
            "Primary provider is unavailable and fallback is not permitted",
            evidence={
                "primary_provider": primary_provider,
                "fallback_allowed": False,
                "rejected_candidates": [asdict(item) for item in rejected],
            },
        )

    fallbacks = [
        record
        for record in eligible
        if record.fallback_eligibility
        and normalize_provider_id(record.provider_id or "") != primary_provider
    ]
    if not fallbacks:
        raise RoutingPolicyError(
            "No eligible policy-governed fallback provider is available",
            evidence={
                "primary_provider": primary_provider,
                "fallback_allowed": True,
                "rejected_candidates": [asdict(item) for item in rejected],
            },
        )

    selected = fallbacks[0]
    remaining = tuple(
        normalize_provider_id(record.provider_id or "")
        for record in fallbacks[1:]
    )
    return selected, primary_provider, remaining, True, rejected


def _routing_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"route-{sha256(canonical.encode('utf-8')).hexdigest()[:20]}"


def route_harness_request(
    request: HarnessRoutingRequest,
    *,
    registry: GlobalCapabilityRegistry = GLOBAL_CAPABILITY_REGISTRY,
) -> HarnessRoutingDecision:
    """Select capability/provider/model/executor metadata without authorizing or executing."""
    if not request.intent or not request.intent.strip():
        raise ValueError("routing intent is required")
    action = request.authorized_action.strip().upper()
    if not action:
        raise ValueError("authorized_action is required")
    if action != request.authorized_action:
        request = HarnessRoutingRequest(
            **{
                **asdict(request),
                "authorized_action": action,
            }
        )

    capability_candidates, rejected, discovered_ids = _capability_candidates(
        request,
        registry,
    )
    if not capability_candidates:
        raise RoutingPolicyError(
            "No executable capability satisfies Harness routing policy",
            evidence={
                "intent": request.intent,
                "authorized_action": action,
                "candidate_capability_ids": list(discovered_ids),
                "rejected_candidates": [asdict(item) for item in rejected],
            },
        )

    capability = capability_candidates[0]
    provider, primary_provider, fallback_candidates, fallback_occurred, provider_rejections = (
        _select_provider(request, registry)
    )
    rejected.extend(provider_rejections)

    selected_provider = (
        normalize_provider_id(provider.provider_id or "")
        if provider is not None
        else None
    )
    selected_model = provider.model_id if provider is not None else None
    evidence_expectations = tuple(
        expectation
        for expectation in (
            capability.evidence_contract,
            provider.evidence_contract if provider is not None else None,
        )
        if expectation
    )
    rationale = [
        f"capability selected from Registry metadata: {capability.capability_id}",
        f"authorized_action policy matched: {action}",
        "non-AVAILABLE Registry records were excluded",
    ]
    if provider is not None:
        rationale.append(
            f"provider selected by Harness policy: {selected_provider}"
        )
        if selected_model:
            rationale.append(f"model bound by provider metadata: {selected_model}")
    if fallback_occurred:
        rationale.append(
            f"explicit fallback applied from primary provider: {primary_provider}"
        )

    policy_metadata = {
        "domain": request.domain,
        "provider_domain": request.provider_domain if request.provider_required else None,
        "required_policy_tags": list(request.required_policy_tags),
        "required_security_terms": list(request.required_security_terms),
        "quality_requirement": request.quality_requirement,
        "latency_constraint": request.latency_constraint,
        "cost_constraint": request.cost_constraint,
        "quota_constraint": request.quota_constraint,
    }
    fingerprint_payload = {
        "request": asdict(request),
        "selected_capability_id": capability.capability_id,
        "selected_provider": selected_provider,
        "selected_model": selected_model,
        "fallback_candidates": fallback_candidates,
        "fallback_occurred": fallback_occurred,
    }

    return HarnessRoutingDecision(
        routing_id=_routing_id(fingerprint_payload),
        intent=request.intent,
        authorized_action=action,
        candidate_capability_ids=tuple(
            record.capability_id for record in capability_candidates
        ),
        selected_capability_id=capability.capability_id,
        selected_provider=selected_provider,
        selected_model=selected_model,
        selected_executor_binding=capability.executor_binding or "",
        selected_provider_executor_binding=(
            provider.executor_binding if provider is not None else None
        ),
        primary_provider=primary_provider,
        fallback_allowed=request.fallback_allowed,
        fallback_candidates=fallback_candidates,
        fallback_occurred=fallback_occurred,
        evidence_expectations=evidence_expectations,
        rationale=tuple(rationale),
        rejected_candidates=tuple(rejected),
        policy_metadata=policy_metadata,
    )
