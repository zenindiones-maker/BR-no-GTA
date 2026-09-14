from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from app.services.gta6_brain import BrainDecision
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    authorization_to_context,
    validate_harness_authorization,
)
from app.services.harness_execution_result import (
    CanonicalExecutionResult,
    canonical_execution_result,
)


@dataclass(frozen=True)
class ActionResult:
    action: str
    tool: str | None
    success: bool
    result: Any
    harness_decision_id: str | None = None
    execution_id: str | None = None
    evidence: CanonicalExecutionResult | None = None

    @property
    def brain_decision_id(self) -> str | None:
        return self.harness_decision_id


class GTA6ActionDispatcher:
    """Subordinate dispatcher: executes only persisted Harness authorization."""

    ACTION_TO_TOOL = {
        "MONITOR": "br_gta6_monitor_run_once", "RESEARCH": "br_research_run",
        "EDITORIAL": "br_editorial_process_next", "EXECUTION": "br_execution_process_next",
        "YOUTUBE": "br_youtube_publish_next",
    }

    def __init__(self, *, monitor: Callable[..., Any], research: Callable[..., Any],
                 editorial: Callable[..., Any], execution: Callable[..., Any],
                 youtube: Callable[..., Any]):
        self._actions = {
            "MONITOR": (self.ACTION_TO_TOOL["MONITOR"], monitor),
            "RESEARCH": (self.ACTION_TO_TOOL["RESEARCH"], research),
            "EDITORIAL": (self.ACTION_TO_TOOL["EDITORIAL"], editorial),
            "EXECUTION": (self.ACTION_TO_TOOL["EXECUTION"], execution),
            "YOUTUBE": (self.ACTION_TO_TOOL["YOUTUBE"], youtube),
        }

    def dispatch(self, decision: BrainDecision, *, authorization: HarnessAuthorization | dict[str, Any] | str | None = None) -> ActionResult:
        action = decision.action
        if action == "WAIT":
            return ActionResult(action="WAIT", tool=None, success=True, result=None)
        handler = self._actions.get(action)
        if handler is None:
            raise ValueError(f"Unsupported GTA6 Brain action: {action!r}")
        if authorization is None:
            raise PermissionError("Harness authorization is required before dispatch")
        auth = validate_harness_authorization(
            authorization, expected_action=action, expected_subject=f"action:{action}"
        )
        context = authorization_to_context(auth)
        tool_name, operation = handler
        routing_id = auth.lineage.get("routing_id")
        capability_id = (
            auth.lineage.get("selected_capability_id")
            or auth.lineage.get("capability_id")
        )
        executor = auth.lineage.get("selected_executor_binding")
        try:
            if action == "MONITOR":
                result = operation(execution_id=auth.execution_id)
            elif action in {"RESEARCH", "EDITORIAL", "EXECUTION", "YOUTUBE"}:
                result = operation(context)
            else:
                result = operation()
        except Exception as exc:
            error = {"error_type": type(exc).__name__, "error": str(exc)}
            evidence = canonical_execution_result(
                authority=auth.authority,
                authorized_action=auth.authorized_action,
                execution_id=auth.execution_id,
                routing_id=routing_id,
                authorization_id=auth.authorization_id,
                harness_decision_id=auth.harness_decision_id,
                capability_id=capability_id,
                tool=tool_name,
                executor=executor,
                status="FAILED",
                success=False,
                result=error,
                error=error,
            )
            return ActionResult(action=action, tool=tool_name, success=False,
                                result=error,
                                harness_decision_id=auth.harness_decision_id,
                                execution_id=auth.execution_id,
                                evidence=evidence)
        evidence = canonical_execution_result(
            authority=auth.authority,
            authorized_action=auth.authorized_action,
            execution_id=auth.execution_id,
            routing_id=routing_id,
            authorization_id=auth.authorization_id,
            harness_decision_id=auth.harness_decision_id,
            capability_id=capability_id,
            tool=tool_name,
            executor=executor,
            status="SUCCEEDED",
            success=True,
            result=result,
        )
        return ActionResult(action=action, tool=tool_name, success=True, result=result,
                            harness_decision_id=auth.harness_decision_id,
                            execution_id=auth.execution_id,
                            evidence=evidence)

    @staticmethod
    def to_dict(result: ActionResult) -> dict[str, Any]:
        payload = asdict(result)
        payload["brain_decision_id"] = result.harness_decision_id
        return payload
