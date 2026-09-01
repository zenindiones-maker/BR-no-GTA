from typing import Any

from app.database import research_repository
from app.services import idea_service
from app.services.editorial_scorer import evaluate_idea


DECISION_TO_STATUS = {
    "approve": "approved",
    "review": "new",
    "reject": "rejected",
}


def create_idea_from_research(research_item_id: int) -> int:
    """Cria uma ideia a partir de um item de pesquisa."""

    research_item = research_repository.get_research_item(research_item_id)

    if research_item is None:
        raise ValueError("Research item não encontrado.")

    return idea_service.create_idea(
        title=research_item["title"],
        description=research_item["content"],
    )


def evaluate_research_item(
    research_item_id: int,
    *,
    relevance: float,
    novelty: float,
    interest: float,
    click_potential: float,
    timeliness: float,
    source_reliability: float,
    video_potential: float,
) -> dict[str, Any]:
    """
    Cria uma ideia a partir de uma pesquisa, calcula o score editorial
    e aplica a decisão ao status da ideia.
    """

    research_item = research_repository.get_research_item(research_item_id)

    if research_item is None:
        raise ValueError("Research item não encontrado.")

    idea_id = create_idea_from_research(research_item_id)

    evaluation = evaluate_idea(
        relevance=relevance,
        novelty=novelty,
        interest=interest,
        click_potential=click_potential,
        timeliness=timeliness,
        source_reliability=source_reliability,
        video_potential=video_potential,
    )

    score = evaluation["score"]
    decision = evaluation["decision"]

    idea_service.update_score(idea_id, score)
    idea_service.update_status(
        idea_id,
        DECISION_TO_STATUS[decision],
    )

    idea = idea_service.get_idea(idea_id)

    return {
        "research_item_id": research_item_id,
        "idea_id": idea_id,
        "score": score,
        "decision": decision,
        "status": idea["status"] if idea else None,
    }
