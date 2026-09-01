from typing import Any

from app.database import editorial_repository


def get_evaluation(evaluation_id: int) -> dict[str, Any] | None:
    """Retorna uma avaliação editorial pelo ID."""
    return editorial_repository.get_editorial_evaluation(evaluation_id)


def list_evaluations() -> list[dict[str, Any]]:
    """Retorna todas as avaliações editoriais em ordem histórica."""
    return editorial_repository.list_editorial_evaluations()


def list_research_evaluations(
    research_item_id: int,
) -> list[dict[str, Any]]:
    """Retorna todas as avaliações de uma pesquisa."""
    return editorial_repository.list_evaluations_for_research(
        research_item_id
    )


def get_latest_evaluation(
    research_item_id: int,
) -> dict[str, Any] | None:
    """Retorna a avaliação mais recente de uma pesquisa."""
    evaluations = list_research_evaluations(research_item_id)

    if not evaluations:
        return None

    return evaluations[-1]


def list_evaluations_by_decision(
    decision: str,
) -> list[dict[str, Any]]:
    """Retorna avaliações filtradas por decisão editorial."""
    valid_decisions = {"approve", "review", "reject"}

    if decision not in valid_decisions:
        raise ValueError(
            f"Decisão inválida: {decision}. "
            f"Permitidas: {', '.join(sorted(valid_decisions))}"
        )

    return [
        evaluation
        for evaluation in list_evaluations()
        if evaluation["decision"] == decision
    ]
