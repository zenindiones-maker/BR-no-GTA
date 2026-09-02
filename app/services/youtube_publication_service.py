from typing import Any

from app.database.youtube_repository import (
    get_youtube_publication,
    get_youtube_publication_by_video_id,
    insert_youtube_publication,
)
from app.services.youtube_publish_spec_service import (
    create_youtube_publish_spec,
)


def create_youtube_publication(
    video: dict[str, Any],
) -> dict[str, Any]:
    """
    Cria e persiste uma intenção de publicação no YouTube.

    Fluxo:

        Video ready
            ↓
        YouTube Publish Spec
            ↓
        YouTube Publication
            ↓
        status = pending

    Responsabilidades:
    - validar o Video através do Publish Spec;
    - impedir publicação duplicada para o mesmo Video;
    - persistir a intenção de publicação;
    - retornar a Publication persistida.

    Esta camada NÃO:
    - publica no YouTube;
    - chama a Google API;
    - executa OAuth;
    - executa upload;
    - instancia Publisher;
    - altera o Video.
    """

    publish_spec = create_youtube_publish_spec(video)

    video_id = publish_spec["video_id"]
    content_item_id = publish_spec["content_item_id"]

    existing_publication = get_youtube_publication_by_video_id(
        video_id
    )

    if existing_publication is not None:
        raise ValueError(
            "Já existe uma YouTube Publication para o Video: "
            f"{video_id}"
        )

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title=publish_spec["title"],
        description=publish_spec["description"],
        tags=publish_spec["tags"],
        category_id=publish_spec.get("category_id") or "20",
        privacy_status=publish_spec["privacy_status"],
        publish_at=publish_spec.get("publish_at"),
        file_path=publish_spec["file_path"],
        status="pending",
    )

    publication = get_youtube_publication(publication_id)

    if publication is None:
        raise RuntimeError(
            "YouTube Publication não foi encontrada após persistência: "
            f"{publication_id}"
        )

    return publication
