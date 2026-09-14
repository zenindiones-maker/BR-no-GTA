from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.database.gta6_master_agent_repository import create_gta6_master_agent_run
from app.services.ai_provider import AIProvider
from app.services.gta6_action_dispatcher import GTA6ActionDispatcher, ActionResult
from app.services.gta6_brain import BrainDecision, GTA6Brain
from app.services.gta6_monitor_worker_service import execute_gta6_monitor
from app.services.gta6_research_pipeline import run_gta6_research
from app.services.editorial_queue_consumer import process_next_editorial_queue_item
from app.services.production_execution_service import process_next_production_execution
from app.services.google_youtube_publication_service import process_next_youtube_publication
from app.services.harness_authorization_service import (
    HarnessAuthorization, validate_harness_authorization,
)


@dataclass(frozen=True)
class MasterAgentCycleResult:
    decision: BrainDecision
    action: ActionResult


class GTA6MasterAgent:
    """Subordinate decision/execution agent. DeepSeek Harness remains authority."""

    def __init__(self, *, ai_provider: AIProvider | None = None):
        if ai_provider is None:
            raise PermissionError(
                "GTA6MasterAgent requires a Harness-routed AI provider"
            )
        self.ai_provider = ai_provider
        self.brain = GTA6Brain(ai_provider=self.ai_provider)
        self._current_brain_decision = BrainDecision(
            action="WAIT", reason="Nenhuma decisão executada ainda.", priority="LOW", confidence=0.0
        )
        self.dispatcher = GTA6ActionDispatcher(
            monitor=execute_gta6_monitor,
            research=run_gta6_research,
            editorial=lambda context: self._run_editorial_with_brain_context(context),
            execution=process_next_production_execution,
            youtube=process_next_youtube_publication,
        )

    def _run_editorial_with_brain_context(self, execution_context):
        decision = self._current_brain_decision
        return process_next_editorial_queue_item(
            ai_provider=self.ai_provider,
            execution_context=execution_context,
            brain_decision={"action": decision.action, "reason": decision.reason,
                            "priority": decision.priority, "confidence": decision.confidence,
                            **execution_context},
        )

    def recommend(self) -> BrainDecision:
        decision = self.brain.decide()
        self._current_brain_decision = decision
        return decision

    def execute_authorized(self, decision: BrainDecision,
                           authorization: HarnessAuthorization | dict[str, Any] | str) -> MasterAgentCycleResult:
        auth = validate_harness_authorization(
            authorization, expected_action=decision.action, expected_subject=f"action:{decision.action}"
        )
        started_at = datetime.now(timezone.utc).isoformat()
        self._current_brain_decision = decision
        action_result = self.dispatcher.dispatch(decision, authorization=auth)
        completed_at = datetime.now(timezone.utc).isoformat()
        create_gta6_master_agent_run(
            execution_id=auth.execution_id, cycle_number=1, action=decision.action,
            reason=decision.reason, priority=decision.priority, confidence=decision.confidence,
            tool=action_result.tool, success=action_result.success, started_at=started_at,
            completed_at=completed_at, result=action_result.result,
            error_type=(action_result.result.get("error_type") if not action_result.success and isinstance(action_result.result, dict) else None),
            error=(action_result.result.get("error") if not action_result.success and isinstance(action_result.result, dict) else None),
        )
        return MasterAgentCycleResult(decision=decision, action=action_result)

    def run_once(self, *, authorization: HarnessAuthorization | dict[str, Any] | str | None = None) -> MasterAgentCycleResult:
        decision = self.recommend()
        if decision.action == "WAIT":
            return MasterAgentCycleResult(decision=decision, action=ActionResult(action="WAIT", tool=None, success=True, result=None))
        if authorization is None:
            raise PermissionError("Harness authorization is required for Master Agent side effects")
        return self.execute_authorized(decision, authorization)

    @staticmethod
    def to_dict(result: MasterAgentCycleResult) -> dict[str, Any]:
        return asdict(result)
