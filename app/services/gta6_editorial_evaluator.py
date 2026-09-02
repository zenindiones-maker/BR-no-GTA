from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.gta6_knowledge import (
    GTA6_CONFIDENCE_LEVELS,
    GTA6_FACT_TYPES,
)


EDITORIAL_CRITERIA = (
    "relevance",
    "novelty",
    "interest",
    "click_potential",
    "timeliness",
    "source_reliability",
    "video_potential",
)


CONFIDENCE_RELIABILITY = {
    "confirmed": 10.0,
    "probable": 7.5,
    "unconfirmed": 5.0,
    "rumor": 2.5,
}


FACT_TYPE_RELEVANCE = {
    "news": 8.0,
    "gameplay": 9.0,
    "feature": 9.0,
    "release": 10.0,
    "update": 9.0,
    "rumor": 5.0,
    "community": 6.0,
    "culture": 5.0,
}


FACT_TYPE_VIDEO_POTENTIAL = {
    "news": 8.0,
    "gameplay": 9.0,
    "feature": 9.0,
    "release": 10.0,
    "update": 9.0,
    "rumor": 7.0,
    "community": 7.0,
    "culture": 6.0,
}


def evaluate_gta6_research_item(
    research_item: dict[str, Any],
    knowledge: dict[str, Any],
    *,
    existing_research_items: list[dict[str, Any]],
    now: str | None = None,
) -> dict[str, float]:
    """
    Avalia editorialmente um item de pesquisa GTA 6.

    Esta camada é deliberadamente pura:
    - não acessa banco;
    - não acessa rede;
    - não chama o Editorial Service;
    - não calcula o score final;
    - não persiste avaliação.

    Ela apenas transforma o contexto de pesquisa em
    sete critérios editoriais normalizados de 0 a 10.
    """

    _validate_research_item(research_item)
    _validate_knowledge(knowledge)

    if not isinstance(existing_research_items, list):
        raise ValueError(
            "existing_research_items deve ser uma lista."
        )

    current_time = _parse_datetime(
        now
        if now is not None
        else datetime.now(timezone.utc).isoformat()
    )

    return {
        "relevance": _calculate_relevance(knowledge),
        "novelty": _calculate_novelty(
            research_item,
            existing_research_items,
        ),
        "interest": _calculate_interest(
            research_item,
            knowledge,
        ),
        "click_potential": _calculate_click_potential(
            research_item,
            knowledge,
        ),
        "timeliness": _calculate_timeliness(
            research_item,
            current_time,
        ),
        "source_reliability": _calculate_source_reliability(
            knowledge,
        ),
        "video_potential": _calculate_video_potential(
            research_item,
            knowledge,
        ),
    }


def _calculate_relevance(
    knowledge: dict[str, Any],
) -> float:
    fact_type = knowledge["fact_type"]

    return FACT_TYPE_RELEVANCE.get(
        fact_type,
        5.0,
    )


def _calculate_novelty(
    research_item: dict[str, Any],
    existing_research_items: list[dict[str, Any]],
) -> float:
    title = _normalize(research_item["title"])

    if not title:
        return 0.0

    for existing in existing_research_items:
        if not isinstance(existing, dict):
            continue

        existing_title = _normalize(
            existing.get("title", "")
        )

        if existing_title == title:
            return 3.0

    return 10.0


def _calculate_interest(
    research_item: dict[str, Any],
    knowledge: dict[str, Any],
) -> float:
    text = _normalize(
        f'{research_item["title"]} '
        f'{research_item.get("content") or ""}'
    )

    if knowledge["fact_type"] in {
        "release",
        "gameplay",
        "feature",
        "update",
    }:
        base = 8.0
    elif knowledge["fact_type"] == "news":
        base = 7.0
    elif knowledge["fact_type"] == "rumor":
        base = 6.0
    else:
        base = 5.0

    if any(
        marker in text
        for marker in (
            "novo",
            "nova",
            "novidade",
            "revelado",
            "revelada",
            "confirmado",
            "confirmada",
            "mudanca",
            "mudança",
        )
    ):
        base += 1.0

    return min(base, 10.0)


def _calculate_click_potential(
    research_item: dict[str, Any],
    knowledge: dict[str, Any],
) -> float:
    title = _normalize(
        research_item["title"]
    )

    score = 5.0

    if len(title) >= 30:
        score += 1.0

    if any(
        marker in title
        for marker in (
            "gta 6",
            "gta vi",
            "rockstar",
        )
    ):
        score += 1.0

    if knowledge["fact_type"] in {
        "release",
        "gameplay",
        "feature",
        "update",
    }:
        score += 2.0

    return min(score, 10.0)


def _calculate_timeliness(
    research_item: dict[str, Any],
    now: datetime,
) -> float:
    published_at = research_item.get(
        "published_at"
    )

    if not published_at:
        return 5.0

    published = _parse_datetime(
        published_at
    )

    age_hours = (
        now - published
    ).total_seconds() / 3600

    if age_hours <= 6:
        return 10.0

    if age_hours <= 24:
        return 9.0

    if age_hours <= 72:
        return 8.0

    if age_hours <= 168:
        return 7.0

    if age_hours <= 720:
        return 5.0

    if age_hours <= 2160:
        return 3.0

    return 1.0


def _calculate_source_reliability(
    knowledge: dict[str, Any],
) -> float:
    confidence = knowledge["confidence"]

    return CONFIDENCE_RELIABILITY[
        confidence
    ]


def _calculate_video_potential(
    research_item: dict[str, Any],
    knowledge: dict[str, Any],
) -> float:
    score = FACT_TYPE_VIDEO_POTENTIAL.get(
        knowledge["fact_type"],
        5.0,
    )

    content = _normalize(
        f'{research_item["title"]} '
        f'{research_item.get("content") or ""}'
    )

    if any(
        marker in content
        for marker in (
            "gameplay",
            "mecanica",
            "mecânica",
            "missao",
            "missão",
            "mapa",
            "personagem",
            "veiculo",
            "veículo",
            "trailer",
            "update",
            "atualizacao",
            "atualização",
        )
    ):
        score += 1.0

    return min(score, 10.0)


def _validate_research_item(
    research_item: dict[str, Any] | None,
) -> None:
    if not isinstance(research_item, dict):
        raise ValueError(
            "research_item é obrigatório."
        )

    if not isinstance(
        research_item.get("title"),
        str,
    ) or not research_item["title"].strip():
        raise ValueError(
            "research_item.title é obrigatório."
        )

    content = research_item.get("content")

    if content is not None and not isinstance(
        content,
        str,
    ):
        raise ValueError(
            "research_item.content deve ser string ou None."
        )


def _validate_knowledge(
    knowledge: dict[str, Any] | None,
) -> None:
    if not isinstance(knowledge, dict):
        raise ValueError(
            "knowledge é obrigatório."
        )

    fact_type = knowledge.get("fact_type")
    confidence = knowledge.get("confidence")

    if fact_type not in GTA6_FACT_TYPES:
        raise ValueError(
            f"invalid fact_type: {fact_type}"
        )

    if confidence not in GTA6_CONFIDENCE_LEVELS:
        raise ValueError(
            f"invalid confidence: {confidence}"
        )


def _parse_datetime(
    value: str,
) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "data deve ser uma string não vazia."
        )

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            f"data inválida: {value}"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(timezone.utc)


def _normalize(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    return " ".join(
        value.lower().strip().split()
    )
