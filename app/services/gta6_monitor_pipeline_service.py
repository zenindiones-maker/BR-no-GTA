from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.database.gta6_monitor_repository import (
    save_gta6_monitor_state,
)
from app.database.memory_claim_repository import insert_memory_claim
from app.services.gta6_claim_extraction_service import extract_gta6_claims
from app.services.gta6_knowledge import GTA6KnowledgeItem
from app.services.gta6_knowledge_service import create_gta6_knowledge
from app.services.gta6_monitor_service import (
    GTA6MonitorResult,
    monitor_gta6_page,
)


@dataclass(frozen=True)
class GTA6MonitorPipelineResult:
    """Resultado operacional de uma execução do pipeline GTA6."""

    monitor: GTA6MonitorResult
    knowledge_created: bool
    knowledge_id: int | None
    claims_created: int
    memory_claim_ids: list[int]


def run_gta6_monitor_pipeline(
    *,
    url: str,
    monitor,
    previous_hash: str | None,
    knowledge_factory: Callable[
        [GTA6MonitorResult],
        GTA6KnowledgeItem,
    ],
) -> GTA6MonitorPipelineResult:
    """Executa o ciclo monitor → knowledge → claim → memory."""

    monitor_result = monitor_gta6_page(
        monitor=monitor,
        url=url,
        previous_hash=previous_hash,
    )

    save_gta6_monitor_state(
        monitor_result.url,
        monitor_result.change.current_hash,
    )

    if not monitor_result.change.changed:
        return GTA6MonitorPipelineResult(
            monitor=monitor_result,
            knowledge_created=False,
            knowledge_id=None,
            claims_created=0,
            memory_claim_ids=[],
        )

    knowledge = knowledge_factory(monitor_result)

    knowledge_result = create_gta6_knowledge(
        title=knowledge.title,
        summary=knowledge.summary,
        source_name=knowledge.source_name,
        source_url=knowledge.source_url,
        fact_type=knowledge.fact_type,
        confidence=knowledge.confidence,
        published_at=knowledge.published_at,
    )

    claims = extract_gta6_claims(knowledge)

    memory_claim_ids = [
        insert_memory_claim(claim)
        for claim in claims
    ]

    return GTA6MonitorPipelineResult(
        monitor=monitor_result,
        knowledge_created=True,
        knowledge_id=knowledge_result["knowledge_id"],
        claims_created=len(memory_claim_ids),
        memory_claim_ids=memory_claim_ids,
    )
