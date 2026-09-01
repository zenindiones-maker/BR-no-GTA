from typing import Any

from app.database import queue_repository
from app.services.priority_service import evaluate_priority


VALID_DECISIONS = {"approve", "review", "reject"}


def sync_idea_queue(
    *,
    idea_id: int,
    decision: str,
    editorial_score: float,
    timeliness: float,
    interest: float,
    click_potential: float,
    video_potential: float,
) -> dict[str, Any]:
    """
    Sincroniza uma ideia avaliada com a fila editorial.

    approve:
        calcula prioridade e cria ou atualiza a entrada ativa.

    review:
        não cria entrada.
        Se existir entrada ativa, cancela.

    reject:
        não cria entrada.
        Se existir entrada ativa, cancela.
    """

    if decision not in VALID_DECISIONS:
        raise ValueError(f"Decisão editorial inválida: {decision}")

    active_item = queue_repository.get_active_queue_item_by_idea(idea_id)

    # REVIEW e REJECT nunca entram na fila.
    if decision in {"review", "reject"}:
        if active_item is None:
            return {
                "idea_id": idea_id,
                "decision": decision,
                "queued": False,
                "queue_id": None,
                "priority_score": None,
                "priority": None,
                "action": "none",
            }

        queue_id = active_item["id"]

        queue_repository.cancel_active_queue_item_by_idea(
            idea_id
        )

        return {
            "idea_id": idea_id,
            "decision": decision,
            "queued": False,
            "queue_id": queue_id,
            "priority_score": None,
            "priority": None,
            "action": "cancelled",
        }

    # APPROVE: calcula prioridade e sincroniza a fila.
    priority_result = evaluate_priority(
        editorial_score=editorial_score,
        timeliness=timeliness,
        interest=interest,
        click_potential=click_potential,
        video_potential=video_potential,
    )

    priority_score = priority_result["priority_score"]
    priority = priority_result["priority"]

    if active_item is not None:
        queue_id = active_item["id"]

        queue_repository.update_queue_priority(
            queue_id,
            priority_score=priority_score,
            priority=priority,
        )

        action = "updated"
    else:
        queue_id = queue_repository.insert_queue_item(
            idea_id=idea_id,
            priority_score=priority_score,
            priority=priority,
            status="queued",
        )

        action = "created"

    return {
        "idea_id": idea_id,
        "decision": decision,
        "queued": True,
        "queue_id": queue_id,
        "priority_score": priority_score,
        "priority": priority,
        "action": action,
    }
