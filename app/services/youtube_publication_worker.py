from typing import Any

from app.services.youtube_publication_orchestration import (
    make_youtube_publication_public,
    upload_youtube_publication,
)


def execute_youtube_upload(
    *,
    publication_id: int,
    publisher: Any,
) -> dict[str, Any]:
    """
    Executa o upload de uma YouTube Publication para staging privado.

    O worker não conhece:
    - OAuth;
    - Google API;
    - SQLite;
    - detalhes do ciclo de vida.

    A orquestração é responsável pela transição:
        pending -> uploaded
    """

    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError(
            "publication_id must be a positive integer"
        )

    if publisher is None:
        raise ValueError("publisher is required")

    return upload_youtube_publication(
        publication_id=publication_id,
        publisher=publisher,
    )


def execute_youtube_publication(
    *,
    publication_id: int,
    publisher: Any,
) -> dict[str, Any]:
    """
    Torna público um vídeo que já foi enviado ao YouTube.

    A orquestração é responsável pela transição:
        uploaded -> published
    """

    if not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError(
            "publication_id must be a positive integer"
        )

    if publisher is None:
        raise ValueError("publisher is required")

    return make_youtube_publication_public(
        publication_id=publication_id,
        publisher=publisher,
    )
