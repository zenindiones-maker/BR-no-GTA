from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class GTA6EditorialBriefError(ValueError):
    """Erro na criação de uma pauta editorial GTA6."""


@dataclass(frozen=True)
class GTA6EditorialBrief:
    """
    Pauta editorial estruturada para produção de conteúdo GTA6.

    A pauta representa a intenção editorial antes da seleção
    definitiva de mídia e antes da produção do vídeo.
    """

    topic: str
    angle: str
    central_question: str
    hook: str
    facts: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    media_requirements: tuple[str, ...]
    target_duration_seconds: float
    priority_score: float
    trend_score: float


def _require_text(
    value: Any,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GTA6EditorialBriefError(
            f"{field_name} deve ser uma string não vazia."
        )

    return value.strip()


def _require_string_tuple(
    values: Any,
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise GTA6EditorialBriefError(
            f"{field_name} deve ser uma lista ou tupla."
        )

    normalized: list[str] = []

    for value in values:
        if not isinstance(value, str):
            raise GTA6EditorialBriefError(
                f"{field_name} deve conter apenas strings."
            )

        value = value.strip()

        if not value:
            raise GTA6EditorialBriefError(
                f"{field_name} não pode conter valores vazios."
            )

        normalized.append(value)

    return tuple(normalized)


def _validate_score(
    value: Any,
    field_name: str,
) -> float:
    if isinstance(value, bool):
        raise GTA6EditorialBriefError(
            f"{field_name} deve ser numérico."
        )

    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise GTA6EditorialBriefError(
            f"{field_name} deve ser numérico."
        ) from exc

    if not 0.0 <= numeric_value <= 10.0:
        raise GTA6EditorialBriefError(
            f"{field_name} deve estar entre 0 e 10."
        )

    return numeric_value


def create_editorial_brief(
    *,
    topic: str,
    angle: str,
    central_question: str,
    hook: str,
    facts: list[str] | tuple[str, ...],
    evidence_requirements: list[str] | tuple[str, ...],
    media_requirements: list[str] | tuple[str, ...],
    target_duration_seconds: float = 900.0,
    priority_score: float = 0.0,
    trend_score: float = 0.0,
) -> GTA6EditorialBrief:
    """
    Cria uma pauta editorial GTA6 validada.

    Esta função é pura.

    Não:
    - consulta banco;
    - chama APIs;
    - pesquisa YouTube;
    - baixa vídeos;
    - executa IA externa;
    - renderiza;
    - publica.

    Ela somente transforma a intenção editorial em um
    contrato estruturado que as próximas camadas podem consumir.
    """

    normalized_topic = _require_text(
        topic,
        "topic",
    )

    normalized_angle = _require_text(
        angle,
        "angle",
    )

    normalized_question = _require_text(
        central_question,
        "central_question",
    )

    normalized_hook = _require_text(
        hook,
        "hook",
    )

    normalized_facts = _require_string_tuple(
        facts,
        "facts",
    )

    normalized_evidence = _require_string_tuple(
        evidence_requirements,
        "evidence_requirements",
    )

    normalized_media = _require_string_tuple(
        media_requirements,
        "media_requirements",
    )

    if isinstance(
        target_duration_seconds,
        bool,
    ):
        raise GTA6EditorialBriefError(
            "target_duration_seconds deve ser numérico."
        )

    try:
        duration = float(
            target_duration_seconds
        )
    except (TypeError, ValueError) as exc:
        raise GTA6EditorialBriefError(
            "target_duration_seconds deve ser numérico."
        ) from exc

    if duration <= 0:
        raise GTA6EditorialBriefError(
            "target_duration_seconds deve ser maior que zero."
        )

    normalized_priority = _validate_score(
        priority_score,
        "priority_score",
    )

    normalized_trend = _validate_score(
        trend_score,
        "trend_score",
    )

    return GTA6EditorialBrief(
        topic=normalized_topic,
        angle=normalized_angle,
        central_question=normalized_question,
        hook=normalized_hook,
        facts=normalized_facts,
        evidence_requirements=normalized_evidence,
        media_requirements=normalized_media,
        target_duration_seconds=duration,
        priority_score=normalized_priority,
        trend_score=normalized_trend,
    )


def validate_editorial_brief(
    brief: GTA6EditorialBrief,
) -> None:
    """
    Valida integralmente uma pauta editorial já criada.
    """

    if not isinstance(
        brief,
        GTA6EditorialBrief,
    ):
        raise GTA6EditorialBriefError(
            "brief deve ser GTA6EditorialBrief."
        )

    _require_text(
        brief.topic,
        "topic",
    )

    _require_text(
        brief.angle,
        "angle",
    )

    _require_text(
        brief.central_question,
        "central_question",
    )

    _require_text(
        brief.hook,
        "hook",
    )

    _require_string_tuple(
        brief.facts,
        "facts",
    )

    _require_string_tuple(
        brief.evidence_requirements,
        "evidence_requirements",
    )

    _require_string_tuple(
        brief.media_requirements,
        "media_requirements",
    )

    if brief.target_duration_seconds <= 0:
        raise GTA6EditorialBriefError(
            "target_duration_seconds deve ser maior que zero."
        )

    _validate_score(
        brief.priority_score,
        "priority_score",
    )

    _validate_score(
        brief.trend_score,
        "trend_score",
    )


def editorial_brief_to_dict(
    brief: GTA6EditorialBrief,
) -> dict[str, Any]:
    """
    Serializa a pauta para consumo pelas próximas camadas.
    """

    validate_editorial_brief(brief)

    return {
        "topic": brief.topic,
        "angle": brief.angle,
        "central_question": brief.central_question,
        "hook": brief.hook,
        "facts": list(brief.facts),
        "evidence_requirements": list(
            brief.evidence_requirements
        ),
        "media_requirements": list(
            brief.media_requirements
        ),
        "target_duration_seconds": (
            brief.target_duration_seconds
        ),
        "priority_score": brief.priority_score,
        "trend_score": brief.trend_score,
    }
