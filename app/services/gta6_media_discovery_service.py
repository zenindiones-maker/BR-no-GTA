from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


class GTA6MediaDiscoveryError(ValueError):
    """Erro de descoberta de mídia GTA6."""


DEFAULT_SEARCH_QUERIES = (
    "GTA 6 gameplay",
    "GTA VI gameplay",
    "Grand Theft Auto VI gameplay",
    "GTA 6 trailer gameplay",
    "GTA 6 new gameplay",
    "GTA 6 analysis gameplay",
)


GTA6_POSITIVE_MARKERS = (
    "gta 6",
    "gta vi",
    "gta6",
    "grand theft auto vi",
    "grand theft auto 6",
)


GTA6_EXCLUDED_MARKERS = (
    "gta online",
    "grand theft auto online",
    "gta v",
    "gta v enhanced",
    "grand theft auto v",
    "grand theft auto v enhanced",
    "gta iv",
    "grand theft auto iv",
    "gta iii",
    "grand theft auto iii",
    "gta 3",
    "grand theft auto 3",
    "gta vice city",
    "grand theft auto vice city",
    "gta san andreas",
    "grand theft auto san andreas",
    "gta liberty city stories",
    "gta chinatown wars",
    "red dead redemption",
    "red dead redemption 2",
    "red dead online",
    "red dead revolver",
    "bully",
    "max payne",
    "la noire",
)


GTA6_GAMEPLAY_MARKERS = (
    "gameplay",
    "gameplay footage",
    "playthrough",
    "walkthrough",
    "mission",
    "police chase",
    "car chase",
    "driving",
    "combat",
    "shootout",
    "mission gameplay",
    "in game",
    "in-game",
)


GTA6_FOOTAGE_MARKERS = (
    "trailer",
    "extended look",
    "official footage",
    "official gameplay",
    "gameplay video",
    "clip",
    "scene",
    "demo",
)


GTA6_ANALYSIS_MARKERS = (
    "analysis",
    "explained",
    "breakdown",
    "information",
    "news",
    "details",
    "features",
    "mechanics",
    "system",
)


def build_gta6_video_search_queries(
    *,
    topic: str | None = None,
) -> list[str]:
    """
    Constrói consultas exclusivamente relacionadas ao GTA6.

    O serviço apenas define o que pesquisar.
    Não baixa mídia e não chama APIs externas.
    """
    if topic is not None and not isinstance(topic, str):
        raise GTA6MediaDiscoveryError(
            "topic deve ser uma string ou None."
        )

    normalized_topic = (
        topic.strip()
        if isinstance(topic, str)
        else ""
    )

    if normalized_topic:
        return [
            f"GTA 6 {normalized_topic} gameplay",
            f"GTA VI {normalized_topic} gameplay",
            f"Grand Theft Auto VI {normalized_topic} gameplay",
            f"GTA 6 {normalized_topic} footage",
            f"GTA 6 {normalized_topic} analysis",
        ]

    return list(DEFAULT_SEARCH_QUERIES)


def _contains_marker(
    text: str,
    markers: tuple[str, ...],
) -> bool:
    """
    Verifica marcadores sem aceitar falsos positivos por substring.

    Exemplo:
        "gta v" não casa com "gta vi".
    """
    normalized_text = text.strip().lower()

    return any(
        re.search(
            rf"(?<!\w){re.escape(marker)}(?!\w)",
            normalized_text,
        )
        is not None
        for marker in markers
    )


def validate_gta6_media_relevance(
    candidate: dict[str, Any],
) -> bool:
    """
    Determina se um candidato pertence exclusivamente ao GTA6.

    A validação é conservadora:
    uma fonte oficial não transforma conteúdo de outro jogo
    em mídia GTA6.

    Nenhuma rede, banco ou análise de vídeo é executada aqui.
    """
    if not isinstance(candidate, dict):
        raise GTA6MediaDiscoveryError(
            "candidate deve ser um dicionário."
        )

    title = str(
        candidate.get("title", "")
    ).strip().lower()

    description = str(
        candidate.get("description", "")
    ).strip().lower()

    channel_title = str(
        candidate.get("channel_title", "")
    ).strip().lower()

    searchable_text = (
        f"{title} {description} {channel_title}"
    )

    if not _contains_marker(
        searchable_text,
        GTA6_POSITIVE_MARKERS,
    ):
        return False

    if _contains_marker(
        searchable_text,
        GTA6_EXCLUDED_MARKERS,
    ):
        return False

    return True


def classify_gta6_media_role(
    candidate: dict[str, Any],
) -> str:
    """
    Classifica o papel editorial de uma mídia GTA6.

    Retorna:
        gameplay
        footage
        analysis
        unknown
    """
    if not validate_gta6_media_relevance(candidate):
        return "unknown"

    title = str(
        candidate.get("title", "")
    ).strip().lower()

    description = str(
        candidate.get("description", "")
    ).strip().lower()

    searchable_text = f"{title} {description}"

    if _contains_marker(
        searchable_text,
        GTA6_GAMEPLAY_MARKERS,
    ):
        return "gameplay"

    if _contains_marker(
        searchable_text,
        GTA6_FOOTAGE_MARKERS,
    ):
        return "footage"

    if _contains_marker(
        searchable_text,
        GTA6_ANALYSIS_MARKERS,
    ):
        return "analysis"

    return "unknown"


def normalize_video_candidate(
    *,
    title: str,
    url: str,
    source: str = "youtube",
    description: str = "",
    published_at: str | None = None,
    video_id: str | None = None,
    channel_id: str | None = None,
    channel_title: str | None = None,
    source_authority: str = "community",
) -> dict[str, Any]:
    """
    Normaliza um vídeo descoberto pelo Brain.

    Nenhum download é executado aqui.
    """
    if not isinstance(title, str) or not title.strip():
        raise GTA6MediaDiscoveryError(
            "title é obrigatório."
        )

    if not isinstance(url, str) or not url.strip():
        raise GTA6MediaDiscoveryError(
            "url é obrigatória."
        )

    parsed = urlparse(url.strip())

    if parsed.scheme not in {"http", "https"}:
        raise GTA6MediaDiscoveryError(
            "A URL do vídeo deve usar HTTP ou HTTPS."
        )

    if not isinstance(source, str) or not source.strip():
        raise GTA6MediaDiscoveryError(
            "source é obrigatório."
        )

    if (
        not isinstance(source_authority, str)
        or not source_authority.strip()
    ):
        raise GTA6MediaDiscoveryError(
            "source_authority deve ser uma string não vazia."
        )

    candidate = {
        "title": title.strip(),
        "url": url.strip(),
        "source": source.strip().lower(),
        "source_authority": source_authority.strip().lower(),
        "description": (
            description.strip()
            if isinstance(description, str)
            else ""
        ),
        "published_at": published_at,
        "media_type": "video",
        "game": "gta6",
        "status": "discovered",
        "video_id": video_id,
        "channel_id": channel_id,
        "channel_title": channel_title,
    }

    candidate["gta6_relevant"] = validate_gta6_media_relevance(
        candidate
    )

    candidate["media_role"] = classify_gta6_media_role(
        candidate
    )

    return candidate


def rank_video_candidate(
    candidate: dict[str, Any],
    *,
    topic: str | None = None,
) -> float:
    """
    Calcula a pontuação inicial de relevância editorial GTA6.

    Apenas candidatos GTA6 válidos podem receber pontuação.
    """
    if not isinstance(candidate, dict):
        raise GTA6MediaDiscoveryError(
            "candidate deve ser um dicionário."
        )

    if not validate_gta6_media_relevance(candidate):
        return 0.0

    title = str(
        candidate.get("title", "")
    ).lower()

    description = str(
        candidate.get("description", "")
    ).lower()

    searchable_text = f"{title} {description}"

    score = 0.0

    score += 5.0

    if _contains_marker(
        searchable_text,
        GTA6_GAMEPLAY_MARKERS,
    ):
        score += 2.5

    elif _contains_marker(
        searchable_text,
        GTA6_FOOTAGE_MARKERS,
    ):
        score += 2.0

    elif _contains_marker(
        searchable_text,
        GTA6_ANALYSIS_MARKERS,
    ):
        score += 1.0

    if topic:
        normalized_topic = topic.strip().lower()

        if (
            normalized_topic
            and normalized_topic in searchable_text
        ):
            score += 2.5

    return min(score, 10.0)


def discover_gta6_media_candidates(
    results: list[dict[str, Any]],
    *,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    """
    Recebe resultados de uma fonte de pesquisa e transforma
    apenas vídeos GTA6 em candidatos de mídia.

    Conteúdo que não for GTA6 é descartado imediatamente.
    """
    if not isinstance(results, list):
        raise GTA6MediaDiscoveryError(
            "results deve ser uma lista."
        )

    candidates: list[dict[str, Any]] = []

    for result in results:
        if not isinstance(result, dict):
            continue

        title = result.get("title")
        url = result.get("url")

        if not title or not url:
            continue

        candidate = normalize_video_candidate(
            title=title,
            url=url,
            source=result.get(
                "source",
                "youtube",
            ),
            description=result.get(
                "description",
                "",
            ),
            published_at=result.get(
                "published_at"
            ),
            video_id=result.get(
                "video_id"
            ),
            channel_id=result.get(
                "channel_id"
            ),
            channel_title=result.get(
                "channel_title"
            ),
            source_authority=result.get(
                "source_authority",
                "community",
            ),
        )

        if not candidate["gta6_relevant"]:
            continue

        candidate["relevance_score"] = rank_video_candidate(
            candidate,
            topic=topic,
        )

        candidates.append(candidate)

    candidates.sort(
        key=lambda item: item["relevance_score"],
        reverse=True,
    )

    return candidates
