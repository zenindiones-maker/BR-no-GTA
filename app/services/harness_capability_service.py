from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from app.services.global_capability_registry import (
    BLOCKED,
    GLOBAL_CAPABILITY_REGISTRY,
    UNKNOWN,
)
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    resolve_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_execution_result import (
    CanonicalExecutionResult,
    canonical_execution_result,
)
from app.services.harness_routing_policy_service import HarnessRoutingDecision


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
    executor_binding: str | None = None
    implementation: str | None = None
    evidence_contract: str | None = None
    agent_id: str | None = None
    skill_id: str | None = None


CapabilityAuthorization = HarnessAuthorization


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

    def to_canonical_result(
        self,
        *,
        authorization_id: str | None = None,
        routing_id: str | None = None,
        tool: str | None = None,
        operation: str | None = None,
        model: str | None = None,
        executor: str | None = None,
        artifacts: tuple[Any, ...] | list[Any] | None = None,
    ) -> CanonicalExecutionResult:
        """Project capability evidence into the single Harness result envelope."""
        success = self.status == "EXECUTED"
        error = None
        if not success and isinstance(self.result, dict) and self.result.get("error"):
            error = {
                key: self.result[key]
                for key in ("error_type", "error")
                if key in self.result
            }
        return canonical_execution_result(
            authority=self.authority,
            authorized_action=self.authorized_action,
            execution_id=self.execution_id,
            routing_id=routing_id,
            authorization_id=authorization_id,
            harness_decision_id=self.harness_decision_id,
            capability_id=self.capability_id,
            tool=tool,
            operation=operation,
            provider=self.provider,
            model=model,
            executor=executor,
            status=self.status,
            success=success,
            result=self.result,
            evidence={"boundary": self.boundary} if self.boundary else {},
            artifacts=artifacts,
            error=error,
        )


def _to_definition(record) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id=record.capability_id,
        provider=record.provider,
        execution_kind=record.execution_kind,
        allowed_actions=record.allowed_actions,
        tags=record.tags,
        available=record.available,
        execution_enabled=record.execution_enabled,
        boundary=record.boundary,
        executor_binding=record.executor_binding,
        implementation=record.implementation,
        evidence_contract=record.evidence_contract,
        agent_id=record.agent_id,
        skill_id=record.skill_id,
    )


# Compatibility surface for existing bounded capability callers. The global
# registry is the source of truth; execution still uses the established contract.
# Native capabilities remain deny-by-default here and must be added explicitly.
CAPABILITY_CATALOG = tuple(
    _to_definition(record)
    for record in GLOBAL_CAPABILITY_REGISTRY.all()
    if (
        record.capability_id.startswith("addy:")
        or record.provider_id == "higgsfield"
        or record.capability_id == "agent-office.execute"
        or record.capability_id == "gta6.fact-check"
        or record.capability_id == "human.presentation.action-first"
        or record.capability_id == "narration.generate.pt-BR"
        or record.capability_id.startswith("youtube.department.")
        or record.capability_id == "youtube.monetization.observe"
        or record.capability_id == "system.improvement.propose"
        or record.capability_id in {
            "media.discovery",
            "production.plan",
            "qa.preflight",
            "script.generate",
            "video.edit.vedit",
            "media.analysis.cloud",
        }
    )
)
_CAPABILITY_BY_ID = {
    capability.capability_id: capability
    for capability in CAPABILITY_CATALOG
}
_REGISTRY_BY_ID = {
    record.capability_id: record
    for record in GLOBAL_CAPABILITY_REGISTRY.all()
}


def discover_capabilities(
    *,
    intent: str,
    authorized_action: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return compact AVAILABLE registry metadata; never inject skill bodies."""
    return GLOBAL_CAPABILITY_REGISTRY.discover(
        intent=intent,
        authorized_action=authorized_action,
        limit=limit,
    )


def authorize_capability(
    capability_id: str,
    authorization: CapabilityAuthorization,
) -> CapabilityDefinition:
    """Validate Harness authority and action policy before any adapter runs.

    BLOCKED implementations may cross only far enough to return auditable BLOCKED
    evidence. They are never considered executable and their adapter is never called.
    """
    authorization = resolve_harness_authorization(authorization)
    authorization = validate_harness_authorization(
        authorization,
        expected_action=authorization.authorized_action,
        expected_subject=f"capability:{capability_id}",
    )

    capability = _CAPABILITY_BY_ID.get(capability_id)
    record = _REGISTRY_BY_ID.get(capability_id)
    if capability is None or record is None or record.availability == UNKNOWN:
        raise ValueError(f"Capability is not AVAILABLE: {capability_id}")
    if authorization.authorized_action not in capability.allowed_actions:
        raise PermissionError(
            "Capability is not authorized for action "
            f"{authorization.authorized_action!r}"
        )
    if record.availability == BLOCKED:
        return capability
    if not record.execution_enabled or not capability.execution_enabled:
        raise PermissionError(f"Capability is not executable: {capability_id}")
    return capability


def _callable_binding(executor: Callable[..., Any]) -> str:
    module = getattr(executor, "__module__", "")
    name = getattr(executor, "__name__", "")
    return f"{module}.{name}" if module and name else ""


def execute_capability(
    *,
    capability_id: str,
    authorization: CapabilityAuthorization,
    payload: dict[str, Any],
    routing_decision: HarnessRoutingDecision | None = None,
    executor: Callable[[CapabilityDefinition, dict[str, Any]], Any] | None = None,
) -> CapabilityEvidence:
    """Execute after Harness authorization; verify routing when supplied by the Harness boundary."""
    authorization = resolve_harness_authorization(authorization)
    capability = authorize_capability(capability_id, authorization)

    record = _REGISTRY_BY_ID[capability_id]
    if routing_decision is not None:
        if routing_decision.selected_capability_id != capability_id:
            raise PermissionError("Harness routing capability mismatch")
        if routing_decision.authorized_action != authorization.authorized_action:
            raise PermissionError("Harness routing action mismatch")
        if routing_decision.selected_executor_binding != record.executor_binding:
            raise PermissionError("Harness routing executor mismatch")
        selected = routing_decision.policy_metadata.get("selected_implementation")
        if not isinstance(selected, dict):
            raise PermissionError("Harness routing implementation metadata is required")
        if selected.get("implementation") != record.implementation:
            raise PermissionError("Harness routing implementation mismatch")
        if selected.get("executor_binding") != record.executor_binding:
            raise PermissionError("Harness routing implementation executor mismatch")
        if selected.get("evidence_contract") != record.evidence_contract:
            raise PermissionError("Harness routing evidence contract mismatch")
        if selected.get("agent_id") != record.agent_id:
            raise PermissionError("Harness routing agent mismatch")
        if selected.get("skill_id") != record.skill_id:
            raise PermissionError("Harness routing skill mismatch")

    if executor is not None:
        expected_binding = str(record.executor_binding or "")
        actual_binding = _callable_binding(executor)
        if not expected_binding or actual_binding != expected_binding:
            raise PermissionError(
                f"{capability_id} caller executor is not the Registry binding"
            )

    if record.availability == BLOCKED:
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
