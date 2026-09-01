from typing import Any

from app.database import research_repository
from app.services import idea_service
from app.services.editorial_scorer import evaluate_idea


DECISION_TO_STATUS = {
    "approve": "approved",
    "review": "new",
    "reject": "rejected",
}


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
    Orquestra a avaliação editorial de um item de pesquisa.

    Fluxo:
        research_item
            ↓
        idea
            ↓
        editorial scorer
            ↓
        score + decision
            ↓
        idea status
    """

    research_item = research_repository.get_research_item(research_item_id)

    if research_item is None:
        raise ValueError("Research item não encontrado.")

    idea_id = idea_service.create_idea(
        title=research_item["title"],
        description=research_item["content"],
    )

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
    status = DECISION_TO_STATUS[decision]

    idea_service.update_score(idea_id, score)
    idea_service.update_status(idea_id, status)

    idea = idea_service.get_idea(idea_id)

    return {
        "research_item_id": research_item_id,
        "idea_id": idea_id,
        "score": score,
        "decision": decision,
        "status": idea["status"] if idea else None,
    }
