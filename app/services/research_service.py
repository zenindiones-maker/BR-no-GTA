from typing import Any

from app.database import ideas_repository
from app.database import research_repository


def create_idea_from_research(
    research_item_id: int,
    status: str = "new",
) -> int:
    """Cria uma ideia a partir de um item de pesquisa existente."""
    research_item = research_repository.get_research_item(research_item_id)

    if research_item is None:
        raise ValueError(f"Research item não encontrado: {research_item_id}")

    title = research_item["title"].strip()

    if not title:
        raise ValueError("Research item não possui título válido.")

    content = research_item.get("content")

    description = content.strip() if isinstance(content, str) else None

    return ideas_repository.insert_idea(
        title=title,
        description=description,
        status=status,
    )


def get_research_item(research_item_id: int) -> dict[str, Any] | None:
    """Retorna um item de pesquisa pelo ID."""
    return research_repository.get_research_item(research_item_id)
