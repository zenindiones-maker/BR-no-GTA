from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.database.gta6_master_agent_repository import (
    create_gta6_master_agent_run,
)
from app.services.ai_provider import AIProvider
from app.services.ai_provider_factory import create_ai_provider
from app.services.gta6_action_dispatcher import (
    GTA6ActionDispatcher,
    ActionResult,
)
from app.services.gta6_brain import BrainDecision, GTA6Brain
from app.services.gta6_monitor_worker_service import execute_gta6_monitor
from app.services.gta6_research_pipeline import run_gta6_research
from app.services.editorial_queue_consumer import (
    process_next_editorial_queue_item,
)
from app.services.render_worker_service import process_next_render_job
from app.services.google_youtube_publication_service import (
    process_next_youtube_publication,
)


@dataclass(frozen=True)
class MasterAgentCycleResult:
    decision: BrainDecision
    action: ActionResult


class GTA6MasterAgent:
    """Control plane do GTA6 Master Agent."""

    def __init__(
        self,
        *,
        ai_provider: AIProvider | None = None,
    ):
        self.ai_provider = ai_provider or create_ai_provider()

        self.brain = GTA6Brain(
            ai_provider=self.ai_provider,
        )

        self._current_brain_decision = BrainDecision(
            action="WAIT",
            reason="Nenhuma decisão executada ainda.",
            priority="LOW",
            confidence=0.0,
        )

        self.dispatcher = GTA6ActionDispatcher(
            monitor=execute_gta6_monitor,
            research=run_gta6_research,
            editorial=lambda context: self._run_editorial_with_brain_context(context),
            execution=process_next_render_job,
            youtube=process_next_youtube_publication,
        )

    def _run_editorial_with_brain_context(self, execution_context):
        decision = self._current_brain_decision

        return process_next_editorial_queue_item(
            ai_provider=self.ai_provider,
            brain_decision={
                "action": decision.action,
                "reason": decision.reason,
                "priority": decision.priority,
                "confidence": decision.confidence,
                **execution_context,
            },
        )

    def run_once(self) -> MasterAgentCycleResult:
        """
        Executa exatamente um ciclo:

        1. Gera o execution_id do ciclo.
        2. Brain observa o estado.
        3. Brain decide uma ação.
        4. Dispatcher executa somente essa ação.
        5. Persiste decisão + ação + resultado.
        6. Retorna decisão + resultado da ação.
        """
        execution_id = str(uuid4())
        cycle_number = 1
        started_at = datetime.now(timezone.utc).isoformat()

        decision = self.brain.decide()
        self._current_brain_decision = decision

        action_result = self.dispatcher.dispatch(
            decision,
            execution_id=execution_id,
        )

        completed_at = datetime.now(timezone.utc).isoformat()

        create_gta6_master_agent_run(
            execution_id=execution_id,
            cycle_number=cycle_number,
            action=decision.action,
            reason=decision.reason,
            priority=decision.priority,
            confidence=decision.confidence,
            tool=action_result.tool,
            success=action_result.success,
            started_at=started_at,
            completed_at=completed_at,
            result=action_result.result,
            error_type=(
                action_result.result.get("error_type")
                if (
                    not action_result.success
                    and isinstance(action_result.result, dict)
                )
                else None
            ),
            error=(
                action_result.result.get("error")
                if (
                    not action_result.success
                    and isinstance(action_result.result, dict)
                )
                else None
            ),
        )

        return MasterAgentCycleResult(
            decision=decision,
            action=action_result,
        )

    @staticmethod
    def to_dict(
        result: MasterAgentCycleResult,
    ) -> dict[str, Any]:
        return asdict(result)
