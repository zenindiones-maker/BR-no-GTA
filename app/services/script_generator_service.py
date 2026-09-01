from typing import Any

from app.database import ideas_repository
from app.services import research_service


def generate_script_structure(idea_id: int) -> dict[str, Any]:
    """
    Gera uma estrutura editorial de roteiro a partir de uma ideia aprovada.

    Esta camada organiza o contexto editorial, mas não grava o roteiro.
    A persistência continua sendo responsabilidade do script_service.
    """
    idea = ideas_repository.get_idea(idea_id)

    if idea is None:
        raise ValueError("A ideia informada não existe.")

    if idea["status"] != "approved":
        raise ValueError(
            "Só é possível gerar roteiro para uma ideia aprovada."
        )

    title = (idea.get("title") or "").strip()
    description = (idea.get("description") or "").strip()

    if not description:
        raise ValueError(
            "A ideia precisa ter uma descrição utilizável."
        )

    research_context = None
    research_item_id = idea.get("research_item_id")

    if research_item_id is not None:
        research_context = research_service.get_research_item(
            research_item_id
        )

    development = [
        {
            "heading": "Contexto",
            "body": (
                f"Partindo da pauta '{title}', vamos entender "
                f"o que está acontecendo e por que isso importa."
            ),
        },
        {
            "heading": "Análise",
            "body": description,
        },
        {
            "heading": "Impacto",
            "body": (
                "Analisar as principais consequências, mudanças "
                "e pontos que podem afetar o público."
            ),
        },
    ]

    if research_context is not None:
        research_content = (
            research_context.get("content") or ""
        ).strip()

        if research_content:
            development[1]["body"] = (
                f"{description}\n\n"
                f"Contexto de pesquisa: {research_content}"
            )

    return {
        "idea_id": idea_id,
        "title": title,
        "hook": (
            f"Você já parou para pensar no que realmente "
            f"pode mudar com isso em {title}?"
        ),
        "introduction": (
            f"Hoje vamos analisar {title}. "
            f"{description}"
        ),
        "development": development,
        "conclusion": (
            "Depois de analisar os principais pontos, "
            "fica claro que essa pauta merece atenção "
            "pelos seus possíveis impactos."
        ),
        "cta": (
            "Se você quer acompanhar as próximas novidades, "
            "continue acompanhando o canal."
        ),
        "research_context": research_context,
    }
