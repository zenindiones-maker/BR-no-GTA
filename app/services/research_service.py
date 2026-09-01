from typing import Any

from app.database import research_repository


def get_research_item(research_item_id: int) -> dict[str, Any] | None:
    """Retorna um item de pesquisa pelo ID."""
    return research_repository.get_research_item(research_item_id)
