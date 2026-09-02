from typing import Any

from app.services.youtube_publication_orchestration import (
    publish_youtube_publication,
)


def execute_youtube_publication(
    *,
    publication_id: int,
    publisher: Any,
):
    """Executa uma publicação através da orquestração existente.

    O worker não conhece detalhes de OAuth, Google ou persistência.
    Ele apenas valida a entrada e delega a execução.
    """
    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")

    if publisher is None:
        raise ValueError("publisher is required")

    return publish_youtube_publication(
        publication_id=publication_id,
        publisher=publisher,
    )
