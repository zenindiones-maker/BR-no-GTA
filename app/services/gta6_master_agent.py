from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

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
from app.services.execution_cycle_service import run_execution_cycle


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

        self.dispatcher = GTA6ActionDispatcher(
            monitor=execute_gta6_monitor,
            research=run_gta6_research,
            editorial=lambda: process_next_editorial_queue_item(
                ai_provider=self.ai_provider,
            ),
            execution=lambda: run_execution_cycle(
                ai_provider=self.ai_provider,
            ),
        )

    def run_once(self) -> MasterAgentCycleResult:
        """
        Executa exatamente um ciclo:

        1. Brain observa o estado.
        2. Brain decide uma ação.
        3. Dispatcher executa somente essa ação.
        4. Retorna decisão + resultado.
        """
        decision = self.brain.decide()
        action_result = self.dispatcher.dispatch(decision)

        return MasterAgentCycleResult(
            decision=decision,
            action=action_result,
        )

    @staticmethod
    def to_dict(
        result: MasterAgentCycleResult,
    ) -> dict[str, Any]:
        return asdict(result)
