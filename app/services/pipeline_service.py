from typing import Any

from app.services.editorial_service import evaluate_research_item


def process_research_item(
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
    Executa o pipeline editorial completo para um item de pesquisa.

    O pipeline atua apenas como fachada/orquestrador.
    As regras de negócio permanecem nos serviços especializados.
    """

    return evaluate_research_item(
        research_item_id=research_item_id,
        relevance=relevance,
        novelty=novelty,
        interest=interest,
        click_potential=click_potential,
        timeliness=timeliness,
        source_reliability=source_reliability,
        video_potential=video_potential,
    )
