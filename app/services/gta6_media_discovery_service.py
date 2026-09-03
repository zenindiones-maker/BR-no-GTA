from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


class GTA6MediaDiscoveryError(ValueError):
    """Erro de descoberta de mídia GTA6."""


DEFAULT_SEARCH_QUERIES = (
    "GTA 6 gameplay",
    "GTA VI gameplay",
    "GTA 6 trailer gameplay",
    "GTA 6 new gameplay",
    "GTA 6 analysis gameplay",
)


def build_gta6_video_search_queries(
    *,
    topic: str | None = None,
) -> list[str]:
    """
    Constrói consultas de descoberta de vídeos GTA6.

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
            f"GTA 6 {normalized_topic} analysis",
        ]

    return list(DEFAULT_SEARCH_QUERIES)


def normalize_video_candidate(
    *,
    title: str,
    url: str,
    source: str = "youtube",
    description: str = "",
    published_at: str | None = None,
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

    return {
        "title": title.strip(),
        "url": url.strip(),
        "source": source.strip().lower(),
        "description": (
            description.strip()
            if isinstance(description, str)
            else ""
        ),
        "published_at": published_at,
        "media_type": "video",
        "game": "gta6",
        "status": "discovered",
    }


def rank_video_candidate(
    candidate: dict[str, Any],
    *,
    topic: str | None = None,
) -> float:
    """
    Calcula uma pontuação inicial de relevância editorial.

    Esta pontuação é deliberadamente simples:
    a inteligência pesada de seleção de momentos virá depois.
    """
    if not isinstance(candidate, dict):
        raise GTA6MediaDiscoveryError(
            "candidate deve ser um dicionário."
        )

    title = str(candidate.get("title", "")).lower()
    description = str(
        candidate.get("description", "")
    ).lower()

    searchable_text = f"{title} {description}"

    score = 0.0

    gta6_markers = (
        "gta 6",
        "gta vi",
        "gta6",
        "grand theft auto vi",
    )

    if any(marker in searchable_text for marker in gta6_markers):
        score += 4.0

    gameplay_markers = (
        "gameplay",
        "trailer",
        "demo",
        "playthrough",
        "mission",
        "gameplay footage",
    )

    if any(
        marker in searchable_text
        for marker in gameplay_markers
    ):
        score += 3.0

    if topic:
        normalized_topic = topic.strip().lower()

        if normalized_topic and normalized_topic in searchable_text:
            score += 3.0

    return min(score, 10.0)


def discover_gta6_media_candidates(
    results: list[dict[str, Any]],
    *,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    """
    Recebe resultados de uma fonte de pesquisa e transforma
    vídeos encontrados em candidatos de mídia GTA6.

    A função não baixa vídeos.
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
            source=result.get("source", "youtube"),
            description=result.get("description", ""),
            published_at=result.get("published_at"),
        )

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
