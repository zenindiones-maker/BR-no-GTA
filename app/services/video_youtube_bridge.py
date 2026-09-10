from __future__ import annotations

from typing import Any

from app.database.youtube_repository import (
    get_youtube_publication_by_video_id,
    insert_youtube_publication,
)


class VideoYouTubeBridgeError(RuntimeError):
    """Erro na criação da publicação YouTube."""


def create_youtube_publication_from_video(
    video: dict[str, Any],
    *,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "20",
) -> dict[str, Any]:
    if not isinstance(video, dict) or not video:
        raise VideoYouTubeBridgeError(
            "Video inválido."
        )

    video_id = video.get("id")
    content_item_id = video.get("content_item_id")
    title = video.get("title")
    file_path = video.get("file_path")

    if not isinstance(video_id, int) or video_id <= 0:
        raise VideoYouTubeBridgeError(
            "Video não possui id válido."
        )

    if (
        not isinstance(content_item_id, int)
        or content_item_id <= 0
    ):
        raise VideoYouTubeBridgeError(
            "Video não possui content_item_id válido."
        )

    if not isinstance(title, str) or not title.strip():
        raise VideoYouTubeBridgeError(
            "Video não possui título válido."
        )

    existing = get_youtube_publication_by_video_id(
        video_id
    )

    if existing is not None:
        return existing

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title=title.strip(),
        description=description,
        tags=tags or [],
        category_id=category_id,
        privacy_status="private",
        publish_at=None,
        file_path=file_path,
        status="pending",
    )

    from app.database.youtube_repository import (
        get_youtube_publication,
    )

    publication = get_youtube_publication(
        publication_id
    )

    if publication is None:
        raise VideoYouTubeBridgeError(
            "YouTube Publication não encontrada após criação."
        )

    return publication
