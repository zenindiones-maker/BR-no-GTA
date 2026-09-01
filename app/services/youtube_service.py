from typing import Any

from app.database.youtube_repository import (
    get_youtube_publication_by_video_id,
    insert_youtube_publication,
)


ALLOWED_PRIVACY_STATUS = {
    "private",
    "public",
    "unlisted",
}


def create_youtube_publish_spec(
    video: dict[str, Any],
    *,
    title: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "20",
    privacy_status: str = "private",
    publish_at: str | None = None,
) -> dict[str, Any]:
    """
    Cria uma especificação específica de publicação no YouTube.

    O Video fornece a identidade e o arquivo audiovisual.
    Os metadados editoriais do YouTube são fornecidos explicitamente
    nesta camada.

    Esta camada não realiza upload.
    """

    if not isinstance(video, dict) or not video:
        raise ValueError(
            "O video informado é inválido."
        )

    required_fields = [
        "id",
        "content_item_id",
        "title",
        "status",
        "file_path",
    ]

    for field in required_fields:
        if field not in video:
            raise ValueError(
                "O video não possui o campo obrigatório: "
                f"{field}."
            )

    video_id = int(video["id"])
    content_item_id = int(video["content_item_id"])

    file_path = video.get("file_path")

    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError(
            "O vídeo precisa possuir um file_path válido "
            "antes da publicação."
        )

    video_title = video.get("title")

    if not isinstance(video_title, str) or not video_title.strip():
        raise ValueError(
            "O vídeo precisa possuir um título válido."
        )

    resolved_title = (
        title.strip()
        if isinstance(title, str) and title.strip()
        else video_title.strip()
    )

    if not isinstance(description, str):
        raise ValueError(
            "description deve ser uma string."
        )

    if tags is None:
        tags = []

    if not isinstance(tags, list):
        raise ValueError(
            "tags deve ser uma lista."
        )

    if any(not isinstance(tag, str) for tag in tags):
        raise ValueError(
            "Todos os elementos de tags devem ser strings."
        )

    if not isinstance(category_id, str) or not category_id.strip():
        raise ValueError(
            "category_id deve ser uma string não vazia."
        )

    if privacy_status not in ALLOWED_PRIVACY_STATUS:
        raise ValueError(
            "privacy_status inválido."
        )

    return {
        "video_id": video_id,
        "content_item_id": content_item_id,
        "file_path": file_path,
        "title": resolved_title,
        "description": description,
        "tags": list(tags),
        "category_id": category_id,
        "privacy_status": privacy_status,
        "publish_at": publish_at,
    }


def create_youtube_publication(
    publish_spec: dict[str, Any],
) -> dict[str, Any]:
    """
    Persiste uma publicação planejada para o YouTube.

    Não realiza upload.
    """

    if (
        not isinstance(publish_spec, dict)
        or not publish_spec
    ):
        raise ValueError(
            "A especificação de publicação é inválida."
        )

    required_fields = [
        "video_id",
        "content_item_id",
        "title",
        "description",
        "tags",
        "category_id",
        "privacy_status",
    ]

    for field in required_fields:
        if field not in publish_spec:
            raise ValueError(
                "A especificação do YouTube não possui "
                f"o campo obrigatório: {field}."
            )

    video_id = int(publish_spec["video_id"])

    existing = get_youtube_publication_by_video_id(
        video_id
    )

    if existing is not None:
        raise ValueError(
            "O vídeo já possui uma publicação YouTube: "
            f"{existing['id']}."
        )

    tags = publish_spec["tags"]

    if not isinstance(tags, list):
        raise ValueError(
            "tags deve ser uma lista."
        )

    if any(not isinstance(tag, str) for tag in tags):
        raise ValueError(
            "Todos os elementos de tags devem ser strings."
        )

    privacy_status = publish_spec["privacy_status"]

    if privacy_status not in ALLOWED_PRIVACY_STATUS:
        raise ValueError(
            "privacy_status inválido."
        )

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=int(
            publish_spec["content_item_id"]
        ),
        title=str(publish_spec["title"]),
        description=str(
            publish_spec["description"]
        ),
        tags=tags,
        category_id=str(
            publish_spec["category_id"]
        ),
        privacy_status=privacy_status,
        publish_at=publish_spec.get("publish_at"),
        status="pending",
    )

    return {
        **publish_spec,
        "id": publication_id,
        "status": "pending",
        "youtube_video_id": None,
        "youtube_url": None,
        "error": None,
        "published_at": None,
    }
