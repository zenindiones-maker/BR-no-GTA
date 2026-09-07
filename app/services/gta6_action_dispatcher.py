from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from app.services.gta6_brain import BrainDecision


@dataclass(frozen=True)
class ActionResult:
    action: str
    tool: str | None
    success: bool
    result: Any


class GTA6ActionDispatcher:
    """Executa exclusivamente a ação autorizada pelo GTA6 Brain."""

    ACTION_TO_TOOL = {
        "MONITOR": "br_gta6_monitor_run_once",
        "RESEARCH": "br_research_run",
        "EDITORIAL": "br_editorial_process_next",
        "EXECUTION": "br_execution_run_once",
    }

    def __init__(
        self,
        *,
        monitor: Callable[[], Any],
        research: Callable[[], Any],
        editorial: Callable[[], Any],
        execution: Callable[[], Any],
    ):
        self._actions = {
            "MONITOR": (
                "br_gta6_monitor_run_once",
                monitor,
            ),
            "RESEARCH": (
                "br_research_run",
                research,
            ),
            "EDITORIAL": (
                "br_editorial_process_next",
                editorial,
            ),
            "EXECUTION": (
                "br_execution_run_once",
                execution,
            ),
        }

    def dispatch(self, decision: BrainDecision) -> ActionResult:
        action = decision.action

        if action == "WAIT":
            return ActionResult(
                action="WAIT",
                tool=None,
                success=True,
                result=None,
            )

        handler = self._actions.get(action)

        if handler is None:
            raise ValueError(
                f"Unsupported GTA6 Brain action: {action!r}"
            )

        tool_name, operation = handler

        try:
            result = operation()
        except Exception as exc:
            return ActionResult(
                action=action,
                tool=tool_name,
                success=False,
                result={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

        return ActionResult(
            action=action,
            tool=tool_name,
            success=True,
            result=result,
        )

    @staticmethod
    def to_dict(result: ActionResult) -> dict[str, Any]:
        return asdict(result)
