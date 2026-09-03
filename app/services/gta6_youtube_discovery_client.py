from __future__ import annotations

from typing import Any

from app.services.google_youtube_client import (
    create_youtube_service,
)


class GTA6YouTubeDiscoveryError(RuntimeError):
    """Erro na descoberta de vídeos GTA6 no YouTube."""


def search_gta6_youtube_videos(
    credentials: Any,
    *,
    query: str,
    max_results: int = 10,
    channel_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Pesquisa vídeos GTA6 no YouTube Data API v3.

    Responsabilidades:
    - receber Credentials já autenticadas;
    - consultar search.list;
    - obter metadados básicos dos vídeos;
    - devolver candidatos normalizados.

    Não é responsabilidade desta função:
    - executar OAuth;
    - carregar tokens;
    - publicar vídeos;
    - baixar vídeos;
    - analisar frames;
    - cortar mídia;
    - decidir editorialmente quais vídeos usar.
    """
    if credentials is None:
        raise GTA6YouTubeDiscoveryError(
            "credentials are required"
        )

    if not isinstance(query, str) or not query.strip():
        raise GTA6YouTubeDiscoveryError(
            "query é obrigatória."
        )

    if (
        not isinstance(max_results, int)
        or isinstance(max_results, bool)
        or max_results <= 0
        or max_results > 50
    ):
        raise GTA6YouTubeDiscoveryError(
            "max_results deve ser um inteiro entre 1 e 50."
        )

    if channel_id is not None:
        if not isinstance(channel_id, str) or not channel_id.strip():
            raise GTA6YouTubeDiscoveryError(
                "channel_id deve ser uma string não vazia ou None."
            )

        channel_id = channel_id.strip()

    youtube = create_youtube_service(credentials)

    try:
        response = (
            youtube.search()
            .list(
                part="snippet",
                q=query.strip(),
                type="video",
                maxResults=max_results,
                order="relevance",
                **(
                    {"channelId": channel_id}
                    if channel_id
                    else {}
                ),
            )
            .execute()
        )
    except Exception as exc:
        raise GTA6YouTubeDiscoveryError(
            f"Falha na pesquisa do YouTube: {exc}"
        ) from exc

    items = response.get("items", [])

    if not isinstance(items, list):
        raise GTA6YouTubeDiscoveryError(
            "Resposta do YouTube possui items inválidos."
        )

    results: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        video_id_data = item.get("id", {})
        snippet = item.get("snippet", {})

        if not isinstance(video_id_data, dict):
            continue

        if not isinstance(snippet, dict):
            continue

        video_id = video_id_data.get("videoId")

        title = snippet.get("title")
        description = snippet.get("description", "")
        published_at = snippet.get("publishedAt")
        channel_id = snippet.get("channelId")
        channel_title = snippet.get("channelTitle")

        if not isinstance(video_id, str) or not video_id:
            continue

        if not isinstance(title, str) or not title.strip():
            continue

        results.append(
            {
                "video_id": video_id,
                "title": title.strip(),
                "url": (
                    "https://www.youtube.com/watch?v="
                    f"{video_id}"
                ),
                "description": (
                    description
                    if isinstance(description, str)
                    else ""
                ),
                "published_at": published_at,
                "channel_id": channel_id,
                "channel_title": channel_title,
                "source": "youtube",
                "media_type": "video",
                "game": "gta6",
                "status": "discovered",
            }
        )

    return results
