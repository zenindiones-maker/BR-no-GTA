from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable
from uuid import uuid4

from app.services.gta6_brain import BrainDecision


@dataclass(frozen=True)
class ActionResult:
    action: str
    tool: str | None
    success: bool
    result: Any
    brain_decision_id: str | None = None
    execution_id: str | None = None


class GTA6ActionDispatcher:
    """Executa exclusivamente a ação autorizada pelo GTA6 Brain."""

    ACTION_TO_TOOL = {
        "MONITOR": "br_gta6_monitor_run_once",
        "RESEARCH": "br_research_run",
        "EDITORIAL": "br_editorial_process_next",
        "EXECUTION": "br_render_process_next",
        "YOUTUBE": "br_youtube_publication_run_once",
    }

    def __init__(
        self,
        *,
        monitor: Callable[[], Any],
        research: Callable[[], Any],
        editorial: Callable[[], Any],
        execution: Callable[[], Any],
        youtube: Callable[[], Any],
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
                "br_render_process_next",
                execution,
            ),
            "YOUTUBE": (
                "br_youtube_publication_run_once",
                youtube,
            ),
        }

    def dispatch(
        self,
        decision: BrainDecision,
        *,
        execution_id: str | None = None,
    ) -> ActionResult:
        action = decision.action
        brain_decision_id = str(uuid4())

        if action == "WAIT":
            return ActionResult(
                action="WAIT",
                tool=None,
                success=True,
                result=None,
                brain_decision_id=brain_decision_id,
                execution_id=execution_id,
            )

        handler = self._actions.get(action)

        if handler is None:
            raise ValueError(
                f"Unsupported GTA6 Brain action: {action!r}"
            )

        tool_name, operation = handler

        try:
            if action in {"EDITORIAL", "EXECUTION"}:
                result = operation(
                    {
                        "brain_decision_id": brain_decision_id,
                        "execution_id": execution_id,
                        "authorized_action": action,
                    }
                )
            else:
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
                brain_decision_id=brain_decision_id,
                execution_id=execution_id,
            )

        return ActionResult(
            action=action,
            tool=tool_name,
            success=True,
            result=result,
            brain_decision_id=brain_decision_id,
            execution_id=execution_id,
        )

    @staticmethod
    def to_dict(result: ActionResult) -> dict[str, Any]:
        return asdict(result)
