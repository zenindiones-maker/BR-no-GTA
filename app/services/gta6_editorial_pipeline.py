from typing import Any

from app.database.editorial_repository import (
    list_evaluations_for_research,
)
from app.database.gta6_knowledge_repository import (
    get_gta6_knowledge,
)
from app.database.research_repository import (
    get_research_item,
    list_research_items,
)
from app.services.gta6_editorial_evaluator import (
    evaluate_gta6_research_item,
)
from app.services.pipeline_service import (
    process_research_item,
)


def process_gta6_research_results(
    results: list[dict[str, Any]],
    *,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """
    Processa resultados da pesquisa GTA 6 através do pipeline editorial.

    Fluxo:

        GTA6 Research
             ↓
        research_item
             ↓
        GTA6 knowledge
             ↓
        idempotência editorial
             ↓
        GTA6 editorial evaluator
             ↓
        pipeline editorial existente
             ↓
        evaluation / idea / queue

    O serviço não pesquisa, não calcula diretamente os critérios
    e não executa produção audiovisual.
    """

    if not isinstance(results, list):
        raise ValueError("results deve ser uma lista.")

    if not results:
        return []

    existing_research_items = list_research_items()
    processed: list[dict[str, Any]] = []

    for result in results:
        research_item_id = result.get("research_item_id")

        if research_item_id is None:
            continue

        evaluations = list_evaluations_for_research(
            research_item_id
        )

        if evaluations:
            continue

        research_item = get_research_item(
            research_item_id
        )

        if research_item is None:
            raise ValueError(
                "Research item não encontrado."
            )

        knowledge_id = result.get("knowledge_id")

        if knowledge_id is None:
            knowledge = None
        else:
            knowledge = get_gta6_knowledge(
                knowledge_id
            )

        if knowledge is None:
            raise ValueError(
                "Conhecimento GTA 6 não encontrado."
            )

        criteria = evaluate_gta6_research_item(
            research_item,
            knowledge,
            existing_research_items=existing_research_items,
            now=now,
        )

        editorial_result = process_research_item(
            research_item_id,
            **criteria,
        )

        processed.append(editorial_result)

    return processed
