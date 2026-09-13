from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from app.services.ai_provider import AIProvider, AIProviderError
from app.services.ai_provider_factory import create_ai_provider
from app.services.nvidia_nim_provider import NvidiaNIMProvider


@dataclass(frozen=True)
class HarnessAIProviderAuthorization:
    authority: str
    authorized_action: str
    harness_decision_id: str
    execution_id: str


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PROVIDER_POLICY = {
    "tuxevil": {"EDITORIAL", "RESEARCH", "EXECUTION", "DEVELOPMENT"},
    "nvidia_nim": {"EDITORIAL", "RESEARCH", "EXECUTION", "DEVELOPMENT"},
}
_PROVIDER_ALIASES = {
    "nvidia": "nvidia_nim",
    "nim": "nvidia_nim",
    "nvidia_nim": "nvidia_nim",
    "tuxevil": "tuxevil",
}


def _validate_authorization(
    provider_name: str,
    authorization: HarnessAIProviderAuthorization,
) -> str:
    if authorization.authority != "deepseek_harness":
        raise PermissionError("DeepSeek Harness is the sole AI provider authority")
    if not authorization.harness_decision_id:
        raise ValueError("harness_decision_id is required")
    if not authorization.execution_id:
        raise ValueError("execution_id is required")

    normalized_provider = _PROVIDER_ALIASES.get(provider_name.strip().lower())
    if normalized_provider is None:
        raise ValueError(f"AI provider is not allowed by Harness policy: {provider_name}")
    if authorization.authorized_action not in _PROVIDER_POLICY[normalized_provider]:
        raise PermissionError(
            "AI provider is not authorized for action "
            f"{authorization.authorized_action!r}"
        )
    return normalized_provider


def select_harness_ai_provider(
    *,
    provider_name: str,
    authorization: HarnessAIProviderAuthorization,
) -> tuple[str, AIProvider]:
    """Select exactly one provider after Harness policy validation."""
    normalized_provider = _validate_authorization(provider_name, authorization)
    if normalized_provider == "nvidia_nim":
        return normalized_provider, NvidiaNIMProvider()
    return normalized_provider, create_ai_provider()


def execute_harness_ai_generation(
    *,
    provider_name: str,
    prompt: str,
    authorization: HarnessAIProviderAuthorization,
    selector: Callable[..., tuple[str, AIProvider]] = select_harness_ai_provider,
) -> HarnessAIProviderEvidence:
    """Harness-owned provider selection, execution, and normalized evidence."""
    normalized_provider, provider = selector(
        provider_name=provider_name,
        authorization=authorization,
    )

    try:
        response = provider.generate(prompt)
    except AIProviderError as exc:
        structured_error = (
            exc.to_dict()
            if callable(getattr(exc, "to_dict", None))
            else {
                "provider": normalized_provider,
                "code": "provider_error",
                "status_code": None,
                "retryable": False,
                "message": str(exc),
            }
        )
        return HarnessAIProviderEvidence(
            provider=normalized_provider,
            status="FAILED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            error=structured_error,
        )

    return HarnessAIProviderEvidence(
        provider=normalized_provider,
        status="EXECUTED",
        active=True,
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result=asdict(response),
    )
