from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class GTA6MediaIntelligenceError(ValueError):
    """Erro na inteligência editorial de mídia GTA6."""


@dataclass(frozen=True)
class GTA6MediaIntelligence:
    """Resultado explicável da inteligência editorial de uma mídia GTA6."""

    topic_relevance: float
    trend_relevance: float
    opportunity_score: float
    evidence_score: float
    authority_score: float
    freshness_score: float
    visual_value: float
    information_value: float
    editorial_relevance: float
    total_score: float
    media_role: str
    editorial_role: str
    reasons: tuple[str, ...]


VALID_MEDIA_ROLES = {
    "gameplay",
    "footage",
    "analysis",
    "unknown",
}

VALID_EDITORIAL_ROLES = {
    "primary_evidence",
    "visual_evidence",
    "context",
    "discovery",
}


AUTHORITY_SCORES = {
    "official": 10.0,
    "primary": 9.0,
    "specialist": 8.0,
    "community": 6.5,
    "unknown": 4.0,
}


GAMEPLAY_SIGNALS = (
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
    "perseguição",
    "polícia",
    "police",
    "chase",
    "mission gameplay",
    "in game",
    "in-game",
)


FOOTAGE_SIGNALS = (
    "trailer",
    "extended look",
    "official footage",
    "official gameplay",
    "gameplay video",
    "clip",
    "scene",
    "demo",
    "teaser",
)


ANALYSIS_SIGNALS = (
    "analysis",
    "analisando",
    "análise",
    "explained",
    "explicado",
    "breakdown",
    "information",
    "informações",
    "news",
    "notícias",
    "details",
    "detalhes",
    "features",
    "recursos",
    "mechanics",
    "mecânicas",
    "system",
    "sistema",
    "curiosidades",
    "everything we learned",
)


TREND_SIGNALS = (
    "new",
    "novo",
    "nova",
    "new system",
    "novo sistema",
    "latest",
    "último",
    "última",
    "recent",
    "recente",
    "today",
    "hoje",
    "breaking",
    "vazou",
    "leaked",
    "leak",
    "exclusive",
    "exclusivo",
    "exclusiva",
    "insane",
    "insano",
    "insana",
    "changed",
    "mudou",
    "vai mudar",
)


def _text(candidate: dict[str, Any]) -> str:
    title = str(candidate.get("title", ""))
    description = str(candidate.get("description", ""))
    channel_title = str(candidate.get("channel_title", ""))

    return (
        f"{title} {description} {channel_title}"
        .strip()
        .lower()
    )


def _contains(text: str, marker: str) -> bool:
    normalized_marker = marker.strip().lower()

    if not normalized_marker:
        return False

    return (
        re.search(
            rf"(?<!\w){re.escape(normalized_marker)}(?!\w)",
            text,
        )
        is not None
    )


def _count_signals(
    text: str,
    signals: tuple[str, ...],
) -> int:
    return sum(
        1
        for signal in signals
        if _contains(text, signal)
    )


def _clamp(value: float) -> float:
    return max(0.0, min(10.0, float(value)))


def _score_topic(
    candidate: dict[str, Any],
    topic: str | None,
) -> float:
    if not isinstance(topic, str) or not topic.strip():
        return 5.0

    normalized_topic = topic.strip().lower()
    text = _text(candidate)

    if _contains(text, normalized_topic):
        return 10.0

    topic_words = [
        word
        for word in re.findall(
            r"\w+",
            normalized_topic,
            flags=re.UNICODE,
        )
        if len(word) >= 3
    ]

    if not topic_words:
        return 5.0

    matches = sum(
        1
        for word in topic_words
        if _contains(text, word)
    )

    ratio = matches / len(topic_words)

    if ratio >= 0.75:
        return 9.0

    if ratio >= 0.50:
        return 7.5

    if ratio > 0:
        return 5.5

    return 2.0


def _score_trend(
    candidate: dict[str, Any],
    *,
    topic: str | None,
    trending_topics: list[str] | tuple[str, ...] | None,
) -> float:
    """
    Mede sinais de oportunidade.

    Importante:
    palavras como "novo" ou "vazou" são apenas sinais.
    Elas não são consideradas prova de tendência.
    A tendência real deverá posteriormente vir do
    Trend Intelligence do Brain.
    """
    text = _text(candidate)

    signal_count = _count_signals(
        text,
        TREND_SIGNALS,
    )

    score = 2.0 + min(
        signal_count * 0.75,
        3.0,
    )

    if isinstance(trending_topics, (list, tuple)):
        normalized_trends = [
            str(item).strip().lower()
            for item in trending_topics
            if str(item).strip()
        ]

        matched_trends = sum(
            1
            for trend in normalized_trends
            if _contains(text, trend)
        )

        score += min(
            matched_trends * 1.5,
            3.0,
        )

    if (
        isinstance(topic, str)
        and topic.strip()
        and _contains(text, topic.strip())
    ):
        score += 1.5

    return _clamp(score)


def _score_freshness(
    candidate: dict[str, Any],
) -> float:
    """
    Frescor básico da fonte.

    A análise temporal completa será responsabilidade do
    Trend Intelligence, que terá histórico e velocidade.
    """
    published_at = candidate.get("published_at")

    if published_at:
        return 8.0

    return 5.0


def _score_authority(
    candidate: dict[str, Any],
) -> float:
    authority = str(
        candidate.get(
            "source_authority",
            "unknown",
        )
    ).strip().lower()

    return AUTHORITY_SCORES.get(
        authority,
        AUTHORITY_SCORES["unknown"],
    )


def _score_visual(
    candidate: dict[str, Any],
) -> float:
    text = _text(candidate)

    gameplay = _count_signals(
        text,
        GAMEPLAY_SIGNALS,
    )

    footage = _count_signals(
        text,
        FOOTAGE_SIGNALS,
    )

    if gameplay >= 2:
        return 10.0

    if gameplay == 1:
        return 8.5

    if footage >= 2:
        return 8.5

    if footage == 1:
        return 7.0

    return 4.0


def _score_information(
    candidate: dict[str, Any],
) -> float:
    text = _text(candidate)

    analysis = _count_signals(
        text,
        ANALYSIS_SIGNALS,
    )

    if analysis >= 3:
        return 10.0

    if analysis == 2:
        return 9.0

    if analysis == 1:
        return 7.5

    return 4.0


def _detect_media_role(
    candidate: dict[str, Any],
) -> str:
    """
    Identifica o que a mídia é.

    Não confundir com a função editorial que o BR
    pretende dar à mídia.
    """
    existing_role = str(
        candidate.get(
            "media_role",
            "",
        )
    ).strip().lower()

    if existing_role in VALID_MEDIA_ROLES - {"unknown"}:
        return existing_role

    text = _text(candidate)

    gameplay = _count_signals(
        text,
        GAMEPLAY_SIGNALS,
    )

    footage = _count_signals(
        text,
        FOOTAGE_SIGNALS,
    )

    analysis = _count_signals(
        text,
        ANALYSIS_SIGNALS,
    )

    scores = {
        "gameplay": gameplay,
        "footage": footage,
        "analysis": analysis,
    }

    best_role = max(
        scores,
        key=scores.get,
    )

    if scores[best_role] == 0:
        return "unknown"

    return best_role


def _detect_editorial_role(
    candidate: dict[str, Any],
    *,
    evidence_score: float,
    visual_score: float,
    information_score: float,
) -> str:
    """
    Define como a mídia deve ser utilizada editorialmente.
    """
    authority = str(
        candidate.get(
            "source_authority",
            "unknown",
        )
    ).strip().lower()

    if (
        authority in {"official", "primary"}
        and evidence_score >= 8.0
    ):
        return "primary_evidence"

    if visual_score >= 8.0:
        return "visual_evidence"

    if information_score >= 7.5:
        return "context"

    return "discovery"


def _score_evidence(
    candidate: dict[str, Any],
    *,
    authority_score: float,
    information_score: float,
) -> float:
    """
    Mede força como evidência.

    Autoridade pesa mais que linguagem promocional.
    """
    reuse_allowed = candidate.get(
        "reuse_allowed",
        False,
    )

    provenance = candidate.get(
        "provenance",
        "",
    )

    score = (
        authority_score * 0.70
        + information_score * 0.20
        + 1.0
    )

    if reuse_allowed:
        score += 0.5

    if isinstance(provenance, str) and provenance.strip():
        score += 0.5

    return _clamp(score)


def _score_opportunity(
    *,
    topic_score: float,
    trend_score: float,
    freshness_score: float,
    visual_score: float,
    information_score: float,
) -> float:
    """
    Mede oportunidade editorial.

    Não confunde oportunidade com confiabilidade.
    """
    return _clamp(
        topic_score * 0.35
        + trend_score * 0.30
        + freshness_score * 0.15
        + visual_score * 0.10
        + information_score * 0.10
    )


def _build_reasons(
    candidate: dict[str, Any],
    *,
    topic_score: float,
    trend_score: float,
    opportunity_score: float,
    evidence_score: float,
    authority_score: float,
    visual_score: float,
    information_score: float,
    media_role: str,
    editorial_role: str,
) -> tuple[str, ...]:
    reasons: list[str] = []

    if topic_score >= 9:
        reasons.append(
            "forte relação com a pauta"
        )
    elif topic_score >= 7:
        reasons.append(
            "relação relevante com a pauta"
        )

    if trend_score >= 8:
        reasons.append(
            "forte oportunidade de tendência"
        )
    elif trend_score >= 6:
        reasons.append(
            "sinais de oportunidade editorial"
        )

    if evidence_score >= 8.5:
        reasons.append(
            "evidência de alta confiabilidade"
        )
    elif evidence_score >= 7:
        reasons.append(
            "evidência de confiabilidade relevante"
        )

    if authority_score >= 9:
        reasons.append(
            "fonte oficial ou primária"
        )
    elif authority_score >= 8:
        reasons.append(
            "fonte especializada"
        )

    if visual_score >= 8:
        reasons.append(
            "alto potencial visual"
        )

    if information_score >= 8:
        reasons.append(
            "alto valor informativo"
        )

    reasons.append(
        f"mídia classificada como {media_role}"
    )

    reasons.append(
        f"uso editorial recomendado: {editorial_role}"
    )

    if opportunity_score >= 8.5:
        reasons.append(
            "alta prioridade para avaliação editorial"
        )

    if not reasons:
        reasons.append(
            "candidato GTA6 sem sinal editorial dominante"
        )

    return tuple(reasons)


def evaluate_gta6_media_intelligence(
    candidate: dict[str, Any],
    *,
    topic: str | None = None,
    trending_topics: list[str] | tuple[str, ...] | None = None,
) -> GTA6MediaIntelligence:
    """
    Analisa uma mídia GTA6 separando:

    - relevância da pauta;
    - oportunidade;
    - evidência;
    - autoridade;
    - frescor;
    - valor visual;
    - valor informativo;
    - função da mídia;
    - função editorial.

    Não baixa vídeo.
    Não chama API.
    Não acessa banco.
    """

    if not isinstance(candidate, dict):
        raise GTA6MediaIntelligenceError(
            "candidate deve ser um dicionário."
        )

    if not candidate.get(
        "gta6_relevant",
        True,
    ):
        raise GTA6MediaIntelligenceError(
            "A mídia precisa ser GTA6 relevante."
        )

    topic_score = _score_topic(
        candidate,
        topic,
    )

    trend_score = _score_trend(
        candidate,
        topic=topic,
        trending_topics=trending_topics,
    )

    freshness_score = _score_freshness(
        candidate,
    )

    authority_score = _score_authority(
        candidate,
    )

    visual_score = _score_visual(
        candidate,
    )

    information_score = _score_information(
        candidate,
    )

    evidence_score = _score_evidence(
        candidate,
        authority_score=authority_score,
        information_score=information_score,
    )

    opportunity_score = _score_opportunity(
        topic_score=topic_score,
        trend_score=trend_score,
        freshness_score=freshness_score,
        visual_score=visual_score,
        information_score=information_score,
    )

    media_role = _detect_media_role(
        candidate,
    )

    editorial_role = _detect_editorial_role(
        candidate,
        evidence_score=evidence_score,
        visual_score=visual_score,
        information_score=information_score,
    )

    editorial_relevance = _clamp(
        opportunity_score * 0.70
        + evidence_score * 0.30
    )

    total_score = _clamp(
        opportunity_score * 0.55
        + evidence_score * 0.25
        + visual_score * 0.10
        + information_score * 0.10
    )

    reasons = _build_reasons(
        candidate,
        topic_score=topic_score,
        trend_score=trend_score,
        opportunity_score=opportunity_score,
        evidence_score=evidence_score,
        authority_score=authority_score,
        visual_score=visual_score,
        information_score=information_score,
        media_role=media_role,
        editorial_role=editorial_role,
    )

    return GTA6MediaIntelligence(
        topic_relevance=round(topic_score, 2),
        trend_relevance=round(trend_score, 2),
        opportunity_score=round(
            opportunity_score,
            2,
        ),
        evidence_score=round(
            evidence_score,
            2,
        ),
        authority_score=round(
            authority_score,
            2,
        ),
        freshness_score=round(
            freshness_score,
            2,
        ),
        visual_value=round(
            visual_score,
            2,
        ),
        information_value=round(
            information_score,
            2,
        ),
        editorial_relevance=round(
            editorial_relevance,
            2,
        ),
        total_score=round(
            total_score,
            2,
        ),
        media_role=media_role,
        editorial_role=editorial_role,
        reasons=reasons,
    )


def rank_gta6_media_by_intelligence(
    candidates: list[dict[str, Any]],
    *,
    topic: str | None = None,
    trending_topics: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """
    Ordena candidatos GTA6 pela inteligência editorial.

    O candidato original é preservado.
    """

    if not isinstance(candidates, list):
        raise GTA6MediaIntelligenceError(
            "candidates deve ser uma lista."
        )

    ranked: list[dict[str, Any]] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        intelligence = evaluate_gta6_media_intelligence(
            candidate,
            topic=topic,
            trending_topics=trending_topics,
        )

        enriched = dict(candidate)

        enriched.update(
            {
                "topic_relevance": (
                    intelligence.topic_relevance
                ),
                "trend_relevance": (
                    intelligence.trend_relevance
                ),
                "opportunity_score": (
                    intelligence.opportunity_score
                ),
                "evidence_score": (
                    intelligence.evidence_score
                ),
                "authority_score": (
                    intelligence.authority_score
                ),
                "freshness_score": (
                    intelligence.freshness_score
                ),
                "visual_value": (
                    intelligence.visual_value
                ),
                "information_value": (
                    intelligence.information_value
                ),
                "editorial_relevance": (
                    intelligence.editorial_relevance
                ),
                "intelligence_score": (
                    intelligence.total_score
                ),
                "media_role": (
                    intelligence.media_role
                ),
                "editorial_role": (
                    intelligence.editorial_role
                ),
                "intelligence_reasons": list(
                    intelligence.reasons
                ),
            }
        )

        ranked.append(enriched)

    ranked.sort(
        key=lambda item: (
            float(
                item.get(
                    "intelligence_score",
                    0.0,
                )
            ),
            float(
                item.get(
                    "evidence_score",
                    0.0,
                )
            ),
            float(
                item.get(
                    "opportunity_score",
                    0.0,
                )
            ),
            float(
                item.get(
                    "relevance_score",
                    0.0,
                )
            ),
        ),
        reverse=True,
    )

    return ranked
