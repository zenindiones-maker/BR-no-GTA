from __future__ import annotations

from typing import Any

from app.services.gta6_media_discovery_service import (
    build_gta6_video_search_queries,
    discover_gta6_media_candidates,
)
from app.services.gta6_youtube_discovery_client import (
    search_gta6_youtube_videos,
)
from app.services.google_oauth import (
    get_youtube_credentials,
)
from app.services.google_youtube_configuration import (
    get_youtube_client_secrets_file,
    get_youtube_token_file,
)
from app.settings import settings


class GTA6MediaDiscoveryPipelineError(RuntimeError):
    """Erro no pipeline de descoberta de mídia GTA6."""


def run_gta6_media_discovery(
    *,
    topic: str | None = None,
    max_results_per_query: int = 10,
) -> list[dict[str, Any]]:
    """
    Executa a descoberta real de vídeos GTA6.

    Fluxo:

        Google OAuth
             ↓
        YouTube Discovery
             ↓
        candidatos brutos
             ↓
        Media Discovery Service
             ↓
        candidatos ranqueados

    Este pipeline não baixa vídeos.
    """
    queries = build_gta6_video_search_queries(
        topic=topic,
    )

    try:
        credentials = get_youtube_credentials(
            token_file=get_youtube_token_file(),
            client_secrets_file=get_youtube_client_secrets_file(),
        )
    except Exception as exc:
        raise GTA6MediaDiscoveryPipelineError(
            f"Não foi possível obter credenciais do YouTube: {exc}"
        ) from exc

    raw_results: list[dict[str, Any]] = []

    # 1. Fontes oficiais: prioridade máxima.
    # A busca é restrita ao canal oficial da Rockstar Games.
    official_queries = [
        (
            f"GTA 6 {topic.strip()}"
            if isinstance(topic, str) and topic.strip()
            else "GTA 6"
        ),
        (
            f"GTA VI {topic.strip()}"
            if isinstance(topic, str) and topic.strip()
            else "GTA VI"
        ),
    ]

    for channel_id in settings.GTA6_OFFICIAL_YOUTUBE_CHANNEL_IDS:
        for query in official_queries:
            try:
                results = search_gta6_youtube_videos(
                    credentials,
                    query=query,
                    max_results=max_results_per_query,
                    channel_id=channel_id,
                )
            except Exception as exc:
                raise GTA6MediaDiscoveryPipelineError(
                    "Falha ao pesquisar fonte oficial Rockstar "
                    f"para a consulta '{query}': {exc}"
                ) from exc

            for result in results:
                result["source"] = "rockstar_games"
                result["source_authority"] = "official"

            raw_results.extend(results)

    # 2. Ecossistema GTA6: pesquisa ampla para descobrir
    # fontes secundárias e comunitárias relevantes.
    for query in queries:
        try:
            results = search_gta6_youtube_videos(
                credentials,
                query=query,
                max_results=max_results_per_query,
            )
        except Exception as exc:
            raise GTA6MediaDiscoveryPipelineError(
                "Falha ao pesquisar vídeos para a consulta "
                f"'{query}': {exc}"
            ) from exc

        for result in results:
            result.setdefault(
                "source_authority",
                "community",
            )

        raw_results.extend(results)

    candidates = discover_gta6_media_candidates(
        raw_results,
        topic=topic,
    )

    unique_candidates: list[dict[str, Any]] = []
    seen_video_ids: set[str] = set()

    for candidate in candidates:
        video_id = candidate.get("video_id")

        if isinstance(video_id, str) and video_id:
            if video_id in seen_video_ids:
                continue

            seen_video_ids.add(video_id)

        unique_candidates.append(candidate)

    return unique_candidates
