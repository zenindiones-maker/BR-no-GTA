from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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
from app.services.zero_cost_policy_service import (
    ZERO_COST_OPERATION,
    assess_zero_cost,
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
    "ollama_local": "ollama_local",
    "ollama-local": "ollama_local",
    "local_openweight": "ollama_local",
    "local-openweight": "ollama_local",
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
    zero_cost_operation: bool = False
    exhausted_free_quota_provider_ids: tuple[str, ...] = ()
    task_class: str | None = None
    goal_id: str | None = None
    agent_id: str | None = None
    skill_id: str | None = None
    artifact_ref: str | None = None
    failure_pattern: str | None = None
    learning_required: bool | None = None
    competence_records: tuple[dict[str, Any], ...] = ()
    required_model_capabilities: tuple[str, ...] = ()
    minimum_context_tokens: int | None = None
    tool_use_required: bool = False
    structured_output_required: bool = False


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


def _runtime_provider_binding(provider_id: str) -> dict[str, Any] | None:
    from app.services.provider_health_service import (
        runtime_provider_binding as resolve_runtime_provider_binding,
    )

    return resolve_runtime_provider_binding(provider_id)


def _authorized_provider_model_binding(
    record: CapabilityRecord,
) -> dict[str, Any] | None:
    from app.services.provider_health_service import (
        authorized_provider_model_binding,
    )

    return authorized_provider_model_binding(record)


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

    if candidates and request.competence_records and not request.required_capability_id:
        original_order = {record.capability_id: index for index, record in enumerate(candidates)}

        def competence_key(record: CapabilityRecord) -> tuple[Any, ...]:
            matches = [
                item
                for item in request.competence_records
                if item.get("capability_id") == record.capability_id
                and item.get("evidence_sufficient") is True
                and (request.task_class is None or item.get("task_class") == request.task_class)
                and (request.domain is None or item.get("domain") == request.domain)
            ]
            if not matches:
                return (1, original_order[record.capability_id])
            best = sorted(
                matches,
                key=lambda item: (
                    -float(item.get("success_rate") or 0.0),
                    float(item.get("failure_rate") or 0.0),
                    float(item.get("human_correction_rate") or 0.0),
                    float(item.get("retry_rate") or 0.0),
                    float(item.get("mean_latency_seconds") or 0.0),
                    float(item.get("mean_cost") or 0.0),
                    -int(item.get("tested_cases") or 0),
                    str(item.get("version") or ""),
                ),
            )[0]
            return (
                0,
                -float(best.get("success_rate") or 0.0),
                float(best.get("failure_rate") or 0.0),
                float(best.get("human_correction_rate") or 0.0),
                float(best.get("retry_rate") or 0.0),
                float(best.get("mean_latency_seconds") or 0.0),
                float(best.get("mean_cost") or 0.0),
                -int(best.get("tested_cases") or 0),
                original_order[record.capability_id],
            )

        candidates.sort(key=competence_key)

    return candidates, rejected, tuple(discovered_ids)


def _model_capabilities(record: CapabilityRecord) -> set[str]:
    prefix = "model-capability:"
    return {
        str(tag)[len(prefix):].strip().lower()
        for tag in record.policy_tags
        if str(tag).startswith(prefix)
    }


def _model_context_window(record: CapabilityRecord) -> int | None:
    prefix = "context-window:"
    for requirement in record.requirements:
        value = str(requirement)
        if value.startswith(prefix):
            try:
                return int(value[len(prefix):])
            except ValueError:
                return None
    return None


def _provider_model_competence(
    record: CapabilityRecord,
    request: HarnessRoutingRequest,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in request.competence_records
        if item.get("capability_id") == record.capability_id
        and item.get("evidence_sufficient") is True
        and (
            request.task_class is None
            or item.get("task_class") == request.task_class
        )
    ]
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda item: (
            -float(item.get("success_rate") or 0.0),
            float(item.get("failure_rate") or 0.0),
            float(item.get("retry_rate") or 0.0),
            float(item.get("mean_latency_seconds") or 0.0),
            -float(item.get("confidence") or 0.0),
            -int(item.get("tested_cases") or 0),
        ),
    )[0]


def _provider_records(
    request: HarnessRoutingRequest,
    registry: GlobalCapabilityRegistry,
) -> tuple[list[CapabilityRecord], list[RoutingRejection]]:
    from app.services.provider_health_service import model_health, provider_health

    allowed = {
        normalize_provider_id(provider_id)
        for provider_id in request.allowed_providers
    }
    unavailable = {
        normalize_provider_id(provider_id)
        for provider_id in request.unavailable_provider_ids
    }
    exhausted_free_quota = {
        normalize_provider_id(provider_id)
        for provider_id in request.exhausted_free_quota_provider_ids
    }
    required_caps = {
        str(item).strip().lower()
        for item in request.required_model_capabilities
        if str(item).strip()
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
        binding = _authorized_provider_model_binding(record)
        model_id = str((binding or {}).get("model_id") or "")
        capabilities = _model_capabilities(record)
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
        if request.preferred_models and model_id not in request.preferred_models:
            reasons.append("model_not_allowed_by_request")
        if required_caps and not required_caps.issubset(capabilities):
            reasons.append("required_model_capabilities_missing")
        if request.tool_use_required and not (
            {"tool_use", "agentic_tool_use"} & capabilities
        ):
            reasons.append("tool_use_required")
        if (
            request.structured_output_required
            and "structured_output" not in capabilities
        ):
            reasons.append("structured_output_required")
        context_window = _model_context_window(record)
        if (
            request.minimum_context_tokens is not None
            and (
                context_window is None
                or context_window < int(request.minimum_context_tokens)
            )
        ):
            reasons.append("context_requirement_not_met")
        if not _record_matches_security(record, request):
            reasons.append("security_boundary_mismatch")

        p_health = provider_health(provider_id, registry=registry)
        if p_health.state in {"BLOCKED", "QUARANTINED", "UPSTREAM_DENIED"}:
            reasons.append(f"provider_health={p_health.state}")
        if (
            provider_id == "nvidia_nim"
            and p_health.state == "AUTH_REQUIRED"
        ):
            reasons.append("provider_health=AUTH_REQUIRED")
        if model_id:
            m_health = model_health(provider_id, model_id, registry=registry)
            if (
                str(getattr(record,"health_policy","") or "").upper()
                == "PROVIDER_AND_MODEL_RUNTIME_HEALTH"
                and m_health.availability != "AVAILABLE"
            ):
                reasons.append(
                    "model_live_runtime_proof_required:"
                    + str(m_health.availability)
                )
            if m_health.circuit_breaker_state == "OPEN":
                reasons.append("model_circuit_breaker_open")
            if m_health.rate_limit_state in {
                "RATE_LIMITED",
                "THROTTLED",
                "EXHAUSTED",
                "BLOCKED",
            }:
                reasons.append(
                    "model_rate_limit_state="
                    + m_health.rate_limit_state
                )
            if m_health.quota_state in {"EXHAUSTED", "BLOCKED"}:
                reasons.append(
                    "model_quota_state=" + m_health.quota_state
                )
            if m_health.availability in {
                "BLOCKED", "QUARANTINED", "UPSTREAM_DENIED"
            }:
                reasons.append(f"model_health={m_health.availability}")
        elif required_caps or request.preferred_models:
            reasons.append("missing_model_binding")

        if request.zero_cost_operation:
            runtime_zero_cost = bool(
                binding is not None
                and binding.get("source") == "CURRENT_RUN_RUNTIME_PROOF"
            )
            if not runtime_zero_cost:
                assessment = assess_zero_cost(
                    record.cost_class,
                    quota_available=(
                        provider_id not in exhausted_free_quota
                    ),
                )
                if not assessment.eligible:
                    reasons.append(
                        assessment.reason.value
                        if assessment.reason
                        else "ZERO_COST_POLICY_BLOCKED"
                    )
        if reasons:
            rejected.append(
                RoutingRejection(record.capability_id, "provider", tuple(reasons))
            )
        else:
            eligible.append(record)

    preference = {
        normalize_provider_id(provider_id): index
        for index, provider_id in enumerate(request.preferred_providers)
    }
    model_preference = {
        model_id: index
        for index, model_id in enumerate(request.preferred_models)
    }
    health_rank = {
        "AVAILABLE": 0,
        "DEGRADED": 1,
        "AUTH_REQUIRED": 2,
        "UNKNOWN/UNPROVEN": 3,
    }
    cost_rank = {
        "FREE_NO_BILLING": 0,
        "FREE_ENDPOINT": 0,
        "FREE_QUOTA_LIMITED": 1,
    }
    rate_limit_rank = {
        "CLEAR": 0,
        "UNKNOWN": 1,
        "OBSERVED": 2,
        "THROTTLED": 3,
        "RATE_LIMITED": 4,
        "EXHAUSTED": 5,
        "BLOCKED": 6,
    }
    quota_rank = {
        "AVAILABLE": 0,
        "AVAILABLE_UNMEASURED": 1,
        "UNKNOWN": 2,
        "THROTTLED": 3,
        "EXHAUSTED": 4,
        "BLOCKED": 5,
    }
    requested_caps_for_rank = set(required_caps)
    if request.tool_use_required:
        requested_caps_for_rank.add("tool_use")
    if request.structured_output_required:
        requested_caps_for_rank.add("structured_output")

    def rank(record: CapabilityRecord) -> tuple[Any, ...]:
        provider_id = normalize_provider_id(record.provider_id or "")
        binding = _authorized_provider_model_binding(record) or {}
        model_id = str(binding.get("model_id") or "")
        p_health = provider_health(provider_id, registry=registry)
        m_health = model_health(provider_id, model_id, registry=registry) if model_id else None
        competence = _provider_model_competence(record, request)
        capabilities = _model_capabilities(record)
        capability_surplus = (
            len(capabilities - requested_caps_for_rank)
            if requested_caps_for_rank
            else 0
        )
        learned_latency = (competence or {}).get("mean_latency_seconds")
        latency = (
            float(learned_latency)
            if isinstance(learned_latency, (int, float))
            else float(m_health.latency_ms) / 1000.0
            if m_health is not None and m_health.latency_ms is not None
            else 1e9
        )
        return (
            preference.get(provider_id, len(preference) + 1),
            model_preference.get(model_id, len(model_preference) + 1),
            health_rank.get(
                m_health.availability if m_health else p_health.state, 9
            ),
            quota_rank.get(
                m_health.quota_state if m_health else "UNKNOWN",
                9,
            ),
            rate_limit_rank.get(
                m_health.rate_limit_state if m_health else "UNKNOWN",
                9,
            ),
            capability_surplus,
            1 if competence is None else 0,
            -float((competence or {}).get("success_rate") or 0.0),
            float((competence or {}).get("failure_rate") or 0.0),
            float((competence or {}).get("retry_rate") or 0.0),
            -float((competence or {}).get("confidence") or 0.0),
            -int((competence or {}).get("tested_cases") or 0),
            cost_rank.get(str(record.cost_class).upper(), 9),
            latency,
            _MATURITY_RANK.get(record.maturity, 99),
            record.capability_id,
        )

    eligible.sort(key=rank)
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
    preferred = tuple(
        normalize_provider_id(item) for item in request.preferred_providers
    )
    primary_provider = (
        preferred[0]
        if preferred
        else normalize_provider_id(eligible[0].provider_id or "")
        if eligible
        else None
    )
    primary_candidates = [
        record
        for record in eligible
        if normalize_provider_id(record.provider_id or "")
        == (primary_provider or "")
    ]
    if primary_candidates:
        selected = primary_candidates[0]
        fallback_candidates = ()
        if request.fallback_allowed:
            fallback_candidates = tuple(dict.fromkeys(
                normalize_provider_id(record.provider_id or "")
                for record in eligible
                if (
                    normalize_provider_id(record.provider_id or "")
                    != primary_provider
                    and record.fallback_eligibility
                )
            ))
        return (
            selected,
            primary_provider,
            fallback_candidates,
            False,
            rejected,
        )

    if not request.fallback_allowed:
        raise RoutingPolicyError(
            "Primary provider is unavailable and fallback is not permitted",
            evidence={
                "primary_provider": primary_provider,
                "fallback_allowed": False,
                "zero_cost_operation": request.zero_cost_operation,
                "rejected_candidates": [
                    asdict(item) for item in rejected
                ],
            },
        )

    fallbacks = [
        record
        for record in eligible
        if (
            record.fallback_eligibility
            and normalize_provider_id(record.provider_id or "")
            != primary_provider
        )
    ]
    if not fallbacks:
        raise RoutingPolicyError(
            "No eligible policy-governed fallback provider is available",
            evidence={
                "primary_provider": primary_provider,
                "fallback_allowed": True,
                "zero_cost_operation": request.zero_cost_operation,
                "rejected_candidates": [
                    asdict(item) for item in rejected
                ],
            },
        )
    selected = fallbacks[0]
    chosen = normalize_provider_id(selected.provider_id or "")
    remaining = tuple(dict.fromkeys(
        normalize_provider_id(record.provider_id or "")
        for record in fallbacks[1:]
        if normalize_provider_id(record.provider_id or "") != chosen
    ))
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


def _apply_global_zero_cost_policy(
    request: HarnessRoutingRequest,
    *,
    authorized_action: str,
) -> HarnessRoutingRequest:
    values = asdict(request)
    values["authorized_action"] = authorized_action
    values["zero_cost_operation"] = bool(
        ZERO_COST_OPERATION or request.zero_cost_operation
    )
    if values == asdict(request):
        return request
    return HarnessRoutingRequest(**values)


def route_harness_request(
    request: HarnessRoutingRequest,
    *,
    registry: GlobalCapabilityRegistry = GLOBAL_CAPABILITY_REGISTRY,
) -> HarnessRoutingDecision:
    """Select capability/provider/model/executor metadata without authorizing or executing.

    Operational learning is part of this normal boundary whenever domain and
    task_class are available. Callers cannot substitute persisted competence
    with self-reported competence in that case.
    """
    if not request.intent or not request.intent.strip():
        raise ValueError("routing intent is required")
    action = request.authorized_action.strip().upper()
    if not action:
        raise ValueError("authorized_action is required")

    has_learning_context = bool(request.domain and request.task_class)
    learning_required = (
        has_learning_context
        if request.learning_required is None
        else bool(request.learning_required)
    )
    if learning_required and not has_learning_context:
        raise RoutingPolicyError(
            "Operational learning requires both domain and task_class",
            evidence={
                "domain": request.domain,
                "task_class": request.task_class,
                "learning_required": True,
            },
        )

    learning_context: dict[str, Any] = {
        "learning_required": learning_required,
        "learning_participated": False,
        "retrieved_memory_ids": [],
        "retrieved_failure_memory_ids": [],
        "retrieved_human_feedback_ids": [],
        "retrieved_human_decision_ids": [],
        "bounded_memory_context": {},
        "competence_records": [],
        "active_skill_versions": [],
        "active_policy_versions": [],
    }
    if has_learning_context:
        try:
            from app.services.harness_learning_context_service import (
                load_operational_learning_context,
            )
            learning_context = {
                "learning_required": learning_required,
                **load_operational_learning_context(
                    domain=str(request.domain),
                    task_class=str(request.task_class),
                    capability_id=request.required_capability_id,
                    agent_id=request.agent_id,
                    skill_id=request.skill_id,
                    goal_id=request.goal_id,
                    artifact_ref=request.artifact_ref,
                    failure_pattern=request.failure_pattern,
                    intent=request.intent,
                ),
            }
        except Exception as exc:
            if learning_required:
                raise RoutingPolicyError(
                    "Operational learning context retrieval failed closed",
                    evidence={
                        "domain": request.domain,
                        "task_class": request.task_class,
                        "error_type": type(exc).__name__,
                    },
                ) from exc
        model_competence: tuple[dict[str, Any], ...] = ()
        if request.provider_required:
            try:
                from app.database import harness_learning_repository as learning_repository
                profile_ids = {
                    record.capability_id
                    for record in registry.all()
                    if record.capability_type == "PROVIDER" and record.model_id
                }
                rows = learning_repository.list_competence(
                    domain=str(request.domain),
                    task_class=str(request.task_class),
                    capability_id=None,
                    agent_id=None,
                    limit=200,
                )
                enriched = []
                for item in rows:
                    if item.get("capability_id") not in profile_ids:
                        continue
                    tested = int(item.get("tested_cases") or 0)
                    enriched.append({
                        **item,
                        "success_rate": (
                            float(item.get("success_count") or 0) / tested
                            if tested else None
                        ),
                        "failure_rate": (
                            float(item.get("failure_count") or 0) / tested
                            if tested else None
                        ),
                        "retry_rate": (
                            float(item.get("retry_count") or 0) / tested
                            if tested else None
                        ),
                        "mean_latency_seconds": (
                            float(item.get("total_latency_seconds") or 0.0) / tested
                            if tested else None
                        ),
                        "mean_cost": (
                            float(item.get("total_cost") or 0.0) / tested
                            if tested else None
                        ),
                        "evidence_sufficient": bool(
                            item.get("status") == "ACTIVE" and tested > 0
                        ),
                    })
                model_competence = tuple(enriched)
            except Exception:
                if learning_required:
                    raise
        learning_context["provider_model_competence_records"] = list(
            model_competence
        )
        if learning_required:
            request = replace(
                request,
                competence_records=tuple([
                    *(learning_context.get("competence_records") or ()),
                    *model_competence,
                ]),
            )

    request = _apply_global_zero_cost_policy(
        request,
        authorized_action=action,
    )

    capability_candidates, rejected, discovered_ids = _capability_candidates(
        request,
        registry,
    )
    if not capability_candidates:
        required_record = (
            registry.get(request.required_capability_id)
            if request.required_capability_id
            else None
        )
        required_state = (
            {
                "capability_id": required_record.capability_id,
                "availability": required_record.availability,
                "maturity": required_record.maturity,
                "status": required_record.status,
                "security_boundary": required_record.security_boundary,
                "executor_binding": required_record.executor_binding,
                "cost_class": required_record.cost_class,
            }
            if required_record is not None
            else None
        )
        raise RoutingPolicyError(
            "No executable capability satisfies Harness routing policy",
            evidence={
                "intent": request.intent,
                "authorized_action": action,
                "zero_cost_operation": request.zero_cost_operation,
                "candidate_capability_ids": list(discovered_ids),
                "rejected_candidates": [asdict(item) for item in rejected],
                "required_capability_state": required_state,
            },
        )

    capability = capability_candidates[0]

    # A provider_id attached to an executable capability identifies the provider
    # of that concrete implementation. It is not, by itself, a request for an
    # ai.provider.* model provider. When the caller's preferred provider is the
    # capability's own bound provider, the Registry executor is sufficient and
    # AI provider/model selection must not be manufactured. Explicit AI-backed
    # capabilities (which do not own that preferred provider identity) continue
    # through _select_provider unchanged.
    capability_provider = (
        normalize_provider_id(capability.provider_id)
        if capability.provider_id
        else None
    )
    preferred_provider_ids = tuple(
        normalize_provider_id(item) for item in request.preferred_providers
    )
    implementation_provider_satisfies_request = bool(
        request.provider_required
        and capability.capability_type in {"EXECUTOR", "CAPABILITY"}
        and capability_provider
        and preferred_provider_ids
        and capability_provider in preferred_provider_ids
    )

    if implementation_provider_satisfies_request:
        provider = None
        primary_provider = None
        fallback_candidates = ()
        fallback_occurred = False
        provider_rejections = []
    else:
        provider, primary_provider, fallback_candidates, fallback_occurred, provider_rejections = (
            _select_provider(request, registry)
        )
    rejected.extend(provider_rejections)

    selected_provider = (
        normalize_provider_id(provider.provider_id or "")
        if provider is not None
        else None
    )
    provider_model_binding = (
        _authorized_provider_model_binding(provider)
        if provider is not None
        else None
    )
    selected_model = (
        str((provider_model_binding or {}).get("model_id") or "") or None
    )
    selected_model_health = None
    if selected_provider and selected_model:
        from app.services.provider_health_service import model_health
        selected_model_health = model_health(
            selected_provider,
            selected_model,
            registry=registry,
        ).to_dict()
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
    if request.zero_cost_operation:
        rationale.append("global ZERO_COST_OPERATION policy enforced")
    selected_competence = [
        item
        for item in request.competence_records
        if item.get("capability_id") == capability.capability_id
        and item.get("evidence_sufficient") is True
        and (request.task_class is None or item.get("task_class") == request.task_class)
    ]
    if selected_competence:
        rationale.append(
            "historical competence evidence participated in Harness routing: "
            f"tested_cases={max(int(item.get('tested_cases') or 0) for item in selected_competence)}"
        )
    if learning_context.get("learning_participated"):
        rationale.append(
            "persisted Harness learning context was retrieved automatically before selection"
        )
    if capability.agent_id or capability.skill_id:
        implementation_identity = capability.skill_id or capability.agent_id or capability.capability_id
        rationale.append(
            "agent/skill implementation selected by Harness policy: "
            f"{capability.capability_type}:{implementation_identity}"
        )
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
        "provider_domain": (
            request.provider_domain
            if request.provider_required and not implementation_provider_satisfies_request
            else None
        ),
        "capability_provider_id": capability.provider_id,
        "implementation_provider_satisfies_request": implementation_provider_satisfies_request,
        "required_policy_tags": list(request.required_policy_tags),
        "required_security_terms": list(request.required_security_terms),
        "quality_requirement": request.quality_requirement,
        "latency_constraint": request.latency_constraint,
        "cost_constraint": request.cost_constraint,
        "quota_constraint": request.quota_constraint,
        "zero_cost_operation": request.zero_cost_operation,
        "global_zero_cost_operation": ZERO_COST_OPERATION,
        "task_class": request.task_class,
        "goal_id": request.goal_id,
        "artifact_ref": request.artifact_ref,
        "failure_pattern": request.failure_pattern,
        "memory_retrieve_before_execution": (
            learning_context.get("MEMORY_RETRIEVE_BEFORE_EXECUTION") == "PASS"
        ),
        "bounded_memory_context": dict(learning_context.get("bounded_memory_context") or {}),
        "learning_context": learning_context,
        "competence_evidence_used": [
            {
                "agent_id": item.get("agent_id"),
                "capability_id": item.get("capability_id"),
                "version": item.get("version"),
                "tested_cases": item.get("tested_cases"),
                "success_rate": item.get("success_rate"),
                "failure_rate": item.get("failure_rate"),
                "human_correction_rate": item.get("human_correction_rate"),
                "retry_rate": item.get("retry_rate"),
                "evidence_refs": item.get("evidence_refs"),
                "last_verified_at": item.get("last_verified_at"),
            }
            for item in request.competence_records
            if item.get("capability_id") == capability.capability_id
            and item.get("evidence_sufficient") is True
        ],
        "selected_provider_cost_class": provider.cost_class if provider is not None else None,
        "selected_model_capabilities": (
            sorted(_model_capabilities(provider))
            if provider is not None else []
        ),
        "selected_model_context_window_tokens": (
            _model_context_window(provider)
            if provider is not None else None
        ),
        "selected_model_health": selected_model_health,
        "provider_model_binding_source": (
            (provider_model_binding or {}).get("source")
        ),
        "runtime_provider_binding_used": (
            (provider_model_binding or {}).get("source")
            == "CURRENT_RUN_RUNTIME_PROOF"
        ),
        "runtime_provider_evidence_refs": list(
            (provider_model_binding or {}).get("evidence_refs") or ()
        ),
        "exhausted_free_quota_provider_ids": list(request.exhausted_free_quota_provider_ids),
        "selected_implementation": {
            "type": capability.capability_type,
            "implementation": capability.implementation,
            "agent_id": capability.agent_id,
            "skill_id": capability.skill_id,
            "executor_binding": capability.executor_binding,
            "evidence_contract": capability.evidence_contract,
            "side_effects": list(capability.side_effects),
            "instruction_path": capability.instruction_path,
        },
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
