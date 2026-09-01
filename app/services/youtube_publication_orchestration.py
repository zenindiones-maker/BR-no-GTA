from typing import Any

from app.database.youtube_repository import (
    get_youtube_publication,
    mark_youtube_published,
    update_youtube_publication_status,
)
from app.services.youtube_publisher import (
    YouTubePublishResult,
    YouTubePublisher,
)


def publish_youtube_publication(
    publication_id: int,
    publisher: YouTubePublisher,
) -> dict[str, Any]:
    """
    Orquestra uma publicação no YouTube.

    Responsabilidades:
    1. Buscar a publicação persistida.
    2. Validar se ela pode ser publicada.
    3. Delegar a publicação ao publisher.
    4. Interpretar o resultado.
    5. Persistir sucesso ou falha.
    6. Retornar o estado persistido.

    A orquestração não conhece Google, OAuth ou detalhes de upload.
    """

    publication = get_youtube_publication(publication_id)

    if publication is None:
        raise ValueError(
            f"YouTube publication not found: {publication_id}"
        )

    if publication["status"] != "pending":
        raise ValueError(
            "YouTube publication is not pending: "
            f"{publication_id}"
        )

    result = publisher.publish(publication)

    if not isinstance(result, YouTubePublishResult):
        raise TypeError(
            "publisher.publish() must return YouTubePublishResult"
        )

    if result.success:
        if not result.youtube_video_id:
            raise ValueError(
                "Successful publication must provide "
                "youtube_video_id"
            )

        if not result.youtube_url:
            raise ValueError(
                "Successful publication must provide "
                "youtube_url"
            )

        updated = mark_youtube_published(
            publication_id,
            result.youtube_video_id,
            result.youtube_url,
        )

        if not updated:
            raise RuntimeError(
                "Failed to persist YouTube publication success: "
                f"{publication_id}"
            )

    else:
        error = result.error or "YouTube publication failed"

        updated = update_youtube_publication_status(
            publication_id,
            "failed",
            error=error,
        )

        if not updated:
            raise RuntimeError(
                "Failed to persist YouTube publication failure: "
                f"{publication_id}"
            )

    persisted_publication = get_youtube_publication(publication_id)

    if persisted_publication is None:
        raise RuntimeError(
            "YouTube publication disappeared after orchestration: "
            f"{publication_id}"
        )

    return persisted_publication
