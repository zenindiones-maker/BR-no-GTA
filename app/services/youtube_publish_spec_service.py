from typing import Any


def create_youtube_publish_spec(video: dict[str, Any]) -> dict[str, Any]:
    """
    Cria a especificação necessária para publicar um Video no YouTube.

    Responsabilidades:
    1. Validar o Video.
    2. Confirmar que o Video está pronto.
    3. Confirmar que existe um arquivo de vídeo.
    4. Transformar os dados do Video em uma especificação de publicação.

    Esta camada não:
    - publica no YouTube;
    - acessa OAuth;
    - acessa a API do YouTube;
    - executa upload;
    - altera o estado do Video;
    - persiste a publicação.
    """

    if not isinstance(video, dict) or not video:
        raise ValueError("O video informado é inválido.")

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
                f"O video não possui o campo obrigatório: {field}."
            )

    video_id = video["id"]

    if not isinstance(video_id, int) or video_id <= 0:
        raise ValueError("video_id must be a positive integer.")

    if video["status"] != "ready":
        raise ValueError(
            f"O video precisa estar ready para publicação: {video_id}"
        )

    file_path = video["file_path"]

    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError(
            f"O video pronto não possui file_path válido: {video_id}"
        )

    title = video["title"]

    if not isinstance(title, str) or not title.strip():
        raise ValueError(
            f"O video não possui título válido: {video_id}"
        )

    content_item_id = video["content_item_id"]

    if (
        not isinstance(content_item_id, int)
        or content_item_id <= 0
    ):
        raise ValueError(
            "content_item_id must be a positive integer."
        )

    return {
        "video_id": video_id,
        "content_item_id": content_item_id,
        "title": title.strip(),
        "description": str(video.get("description") or "").strip(),
        "tags": list(video.get("tags") or []),
        "category_id": video.get("category_id"),
        "privacy_status": video.get(
            "privacy_status",
            "private",
        ),
        "file_path": file_path.strip(),
        "status": "ready",
    }
