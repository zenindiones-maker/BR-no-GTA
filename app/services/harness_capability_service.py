from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


HIGGSFIELD_AUTH_BOUNDARY = (
    "interactive_browser_only_confirmed; unattended ephemeral-runner auth "
    "not officially confirmed"
)


class CapabilityExecutionBlocked(RuntimeError):
    """Safe prerequisite block that must return to the Harness without execution."""

    def __init__(self, safe_message: str, *, stage: str, boundary: str):
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.stage = stage
        self.boundary = boundary


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    provider: str
    execution_kind: str
    allowed_actions: tuple[str, ...]
    tags: tuple[str, ...]
    available: bool = True
    execution_enabled: bool = True
    boundary: str | None = None


@dataclass(frozen=True)
class CapabilityAuthorization:
    authority: str
    authorized_action: str
    harness_decision_id: str
    execution_id: str


@dataclass(frozen=True)
class CapabilityEvidence:
    capability_id: str
    provider: str
    status: str
    active: bool
    authority: str
    authorized_action: str
    harness_decision_id: str
    execution_id: str
    result: Any = None
    boundary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ADDY_SKILLS = (
    "api-and-interface-design",
    "ci-cd-and-automation",
    "code-review-and-quality",
    "code-simplification",
    "constraint-driven-development",
    "context-engineering",
    "debugging-and-error-recovery",
    "deprecation-and-migration",
    "documentation-and-adrs",
    "doubt-driven-development",
    "frontend-ui-engineering",
    "git-workflow-and-versioning",
    "idea-refine",
    "incremental-implementation",
    "interview-me",
    "observability-and-instrumentation",
    "performance-optimization",
    "planning-and-task-breakdown",
    "security-and-hardening",
    "shipping-and-launch",
    "source-driven-development",
    "spec-driven-development",
    "test-driven-development",
    "using-agent-skills",
)


HIGGSFIELD_CAPABILITIES = (
    CapabilityDefinition(
        capability_id="higgsfield-generate",
        provider="higgsfield",
        execution_kind="higgsfield_cli",
        allowed_actions=("EXECUTION",),
        tags=("image", "video", "creative", "generation"),
        execution_enabled=False,
        boundary=HIGGSFIELD_AUTH_BOUNDARY,
    ),
    CapabilityDefinition(
        capability_id="higgsfield-youtube-thumbnail",
        provider="higgsfield",
        execution_kind="higgsfield_cli",
        allowed_actions=("YOUTUBE",),
        tags=("youtube", "thumbnail", "image"),
        execution_enabled=False,
        boundary=HIGGSFIELD_AUTH_BOUNDARY,
    ),
    CapabilityDefinition(
        capability_id="higgsfield-brandkit",
        provider="higgsfield",
        execution_kind="higgsfield_cli",
        allowed_actions=("EDITORIAL", "EXECUTION"),
        tags=("brand", "creative", "design"),
        execution_enabled=False,
        boundary=HIGGSFIELD_AUTH_BOUNDARY,
    ),
    CapabilityDefinition(
        capability_id="higgsfield-video-explainer",
        provider="higgsfield",
        execution_kind="higgsfield_cli",
        allowed_actions=("EXECUTION",),
        tags=("video", "explainer", "creative"),
        execution_enabled=False,
        boundary=HIGGSFIELD_AUTH_BOUNDARY,
    ),
)


def _addy_capabilities() -> tuple[CapabilityDefinition, ...]:
    return tuple(
        CapabilityDefinition(
            capability_id=f"addy:{name}",
            provider="addy-agent-skills",
            execution_kind="codex_native_skill",
            allowed_actions=("DEVELOPMENT",),
            tags=tuple(name.split("-")),
        )
        for name in ADDY_SKILLS
    )


CAPABILITY_CATALOG = _addy_capabilities() + HIGGSFIELD_CAPABILITIES
_CAPABILITY_BY_ID = {
    capability.capability_id: capability
    for capability in CAPABILITY_CATALOG
}


def discover_capabilities(
    *,
    intent: str,
    authorized_action: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return relevant AVAILABLE metadata; never inject skill bodies."""
    if limit < 1:
        raise ValueError("limit must be positive")

    terms = {
        term
        for term in intent.lower().replace("_", "-").split()
        if term
    }
    if not terms:
        return []

    candidates: list[dict[str, Any]] = []
    for capability in CAPABILITY_CATALOG:
        if not capability.available:
            continue
        if (
            authorized_action
            and authorized_action not in capability.allowed_actions
        ):
            continue

        haystack = (
            capability.capability_id.lower(),
            capability.provider.lower(),
            *capability.tags,
        )
        if not any(
            term in value
            for term in terms
            for value in haystack
        ):
            continue

        candidates.append(
            {
                "capability_id": capability.capability_id,
                "provider": capability.provider,
                "execution_kind": capability.execution_kind,
                "allowed_actions": list(capability.allowed_actions),
                "available": capability.available,
                "execution_enabled": capability.execution_enabled,
                "boundary": capability.boundary,
            }
        )
        if len(candidates) >= limit:
            break

    return candidates


def authorize_capability(
    capability_id: str,
    authorization: CapabilityAuthorization,
) -> CapabilityDefinition:
    """Validate Harness authority and action policy before any adapter runs."""
    if authorization.authority != "deepseek_harness":
        raise PermissionError("DeepSeek Harness is the sole capability authority")
    if not authorization.harness_decision_id:
        raise ValueError("harness_decision_id is required")
    if not authorization.execution_id:
        raise ValueError("execution_id is required")

    capability = _CAPABILITY_BY_ID.get(capability_id)
    if capability is None or not capability.available:
        raise ValueError(f"Capability is not AVAILABLE: {capability_id}")
    if authorization.authorized_action not in capability.allowed_actions:
        raise PermissionError(
            "Capability is not authorized for action "
            f"{authorization.authorized_action!r}"
        )
    return capability


def execute_capability(
    *,
    capability_id: str,
    authorization: CapabilityAuthorization,
    payload: dict[str, Any],
    executor: Callable[[CapabilityDefinition, dict[str, Any]], Any] | None = None,
) -> CapabilityEvidence:
    """Execute only after policy validation and return lineage-bearing evidence."""
    capability = authorize_capability(capability_id, authorization)

    if not capability.execution_enabled:
        return CapabilityEvidence(
            capability_id=capability.capability_id,
            provider=capability.provider,
            status="BLOCKED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            boundary=capability.boundary,
        )

    if executor is None:
        return CapabilityEvidence(
            capability_id=capability.capability_id,
            provider=capability.provider,
            status="READY",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            boundary="No capability executor bound by the DeepSeek Harness",
        )

    try:
        result = executor(capability, payload)
    except CapabilityExecutionBlocked as exc:
        return CapabilityEvidence(
            capability_id=capability.capability_id,
            provider=capability.provider,
            status="BLOCKED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={
                "stage": exc.stage,
                "error": exc.safe_message,
            },
            boundary=exc.boundary,
        )
    except Exception as exc:
        safe_error = getattr(
            exc,
            "safe_message",
            "Capability executor failed",
        )
        return CapabilityEvidence(
            capability_id=capability.capability_id,
            provider=capability.provider,
            status="FAILED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={
                "error_type": type(exc).__name__,
                "error": safe_error,
            },
            boundary="Capability executor failed; no fallback executed",
        )

    return CapabilityEvidence(
        capability_id=capability.capability_id,
        provider=capability.provider,
        status="EXECUTED",
        active=True,
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result=result,
    )
