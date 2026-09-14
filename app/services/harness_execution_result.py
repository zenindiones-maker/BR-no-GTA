from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CanonicalExecutionResult:
    """Pure execution-result envelope. It records authority; it never grants it."""

    authority: str | None
    authorized_action: str | None
    execution_id: str | None
    status: str
    success: bool
    result: Any = None
    routing_id: str | None = None
    authorization_id: str | None = None
    harness_decision_id: str | None = None
    capability_id: str | None = None
    tool: str | None = None
    operation: str | None = None
    provider: str | None = None
    model: str | None = None
    executor: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[Any, ...] = ()
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-serializable mapping."""
        return asdict(self)


def canonical_execution_result(
    *,
    result: Any,
    status: str,
    success: bool,
    authority: str | None = None,
    authorized_action: str | None = None,
    execution_id: str | None = None,
    routing_id: str | None = None,
    authorization_id: str | None = None,
    harness_decision_id: str | None = None,
    capability_id: str | None = None,
    tool: str | None = None,
    operation: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    executor: str | None = None,
    evidence: dict[str, Any] | None = None,
    artifacts: tuple[Any, ...] | list[Any] | None = None,
    error: dict[str, Any] | None = None,
) -> CanonicalExecutionResult:
    """Build the canonical envelope without routing, authorizing, or executing."""
    return CanonicalExecutionResult(
        authority=authority,
        authorized_action=authorized_action,
        execution_id=execution_id,
        routing_id=routing_id,
        authorization_id=authorization_id,
        harness_decision_id=harness_decision_id,
        capability_id=capability_id,
        tool=tool,
        operation=operation,
        provider=provider,
        model=model,
        executor=executor,
        status=status,
        success=success,
        result=result,
        evidence=dict(evidence or {}),
        artifacts=tuple(artifacts or ()),
        error=dict(error) if error is not None else None,
    )
