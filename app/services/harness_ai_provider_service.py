from __future__ import annotations

from dataclasses import asdict, dataclass
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
    result: Any = None
    error: Any = None
    routing: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    decision, _, normalized_provider = _resolve_routing(
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
        return normalized_provider, create_ai_provider()

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
    """Execute one routed provider; provider failures never trigger silent fallback."""
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

    try:
        response = provider.generate(prompt)
    except AIProviderError as exc:
        structured_error = (
            exc.to_dict()
            if callable(getattr(exc, "to_dict", None))
            else {
                "provider": expected_provider,
                "code": "provider_error",
                "status_code": None,
                "retryable": False,
                "message": str(exc),
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
            error=structured_error,
            routing=decision.to_dict(),
        )

    return HarnessAIProviderEvidence(
        provider=expected_provider,
        status="EXECUTED",
        active=True,
        authority=resolved_authorization.authority,
        authorized_action=resolved_authorization.authorized_action,
        harness_decision_id=resolved_authorization.harness_decision_id,
        execution_id=resolved_authorization.execution_id,
        result=asdict(response),
        routing=decision.to_dict(),
    )
