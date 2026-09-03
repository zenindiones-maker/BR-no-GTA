from __future__ import annotations

from typing import Any

from app.database.content_segment_repository import (
    get_content_segment,
)
from app.services.episode_service import (
    create_and_persist_episode,
    is_episode_duration_valid,
)
from app.services.episode_segment_service import (
    create_and_persist_episode_segment,
)


class EpisodeCompositionError(ValueError):
    """Erro de composição de Episode."""


def calculate_composition_duration(
    segments: list[dict[str, Any]],
) -> float:
    """
    Calcula a duração total da composição.

    A duração de cada Content Segment é somada na ordem
    em que será utilizado no Episode.
    """
    if not isinstance(segments, list):
        raise EpisodeCompositionError(
            "segments deve ser uma lista."
        )

    total = 0.0

    for segment in segments:
        if not isinstance(segment, dict):
            raise EpisodeCompositionError(
                "Cada segmento da composição deve ser um dicionário."
            )

        duration = segment.get("duration_seconds")

        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration <= 0
        ):
            raise EpisodeCompositionError(
                "Cada segmento deve possuir uma duração positiva."
            )

        total += float(duration)

    return total


def validate_episode_composition(
    *,
    target_duration_seconds: float,
    min_duration_seconds: float,
    max_duration_seconds: float,
    segments: list[dict[str, Any]],
) -> float:
    """
    Valida uma composição antes da persistência.

    Não cria Episode e não acessa o banco.
    """
    if (
        not isinstance(target_duration_seconds, (int, float))
        or isinstance(target_duration_seconds, bool)
        or target_duration_seconds <= 0
    ):
        raise EpisodeCompositionError(
            "target_duration_seconds deve ser positivo."
        )

    if (
        not isinstance(min_duration_seconds, (int, float))
        or isinstance(min_duration_seconds, bool)
        or min_duration_seconds <= 0
    ):
        raise EpisodeCompositionError(
            "min_duration_seconds deve ser positivo."
        )

    if (
        not isinstance(max_duration_seconds, (int, float))
        or isinstance(max_duration_seconds, bool)
        or max_duration_seconds <= 0
    ):
        raise EpisodeCompositionError(
            "max_duration_seconds deve ser positivo."
        )

    if min_duration_seconds > target_duration_seconds:
        raise EpisodeCompositionError(
            "A duração mínima não pode exceder a duração alvo."
        )

    if target_duration_seconds > max_duration_seconds:
        raise EpisodeCompositionError(
            "A duração alvo não pode exceder a duração máxima."
        )

    duration = calculate_composition_duration(segments)

    if not (
        min_duration_seconds
        <= duration
        <= max_duration_seconds
    ):
        raise EpisodeCompositionError(
            "A duração total da composição está fora da janela "
            "permitida do Episode: "
            f"{duration:.2f}s "
            f"(permitido: "
            f"{min_duration_seconds:.2f}s–"
            f"{max_duration_seconds:.2f}s)."
        )

    return duration


def compose_episode(
    *,
    title: str,
    content_segment_ids: list[int],
    target_duration_seconds: float = 900.0,
    min_duration_seconds: float = 840.0,
    max_duration_seconds: float = 960.0,
    status: str = "draft",
) -> dict[str, Any]:
    """
    Compõe e persiste um Episode a partir de Content Segments.

    Fluxo:

        Content Segments
              ↓
        validação
              ↓
        Episode
              ↓
        Episode Segments
              ↓
        composição persistida

    Esta camada NÃO:
    - renderiza;
    - corta arquivos;
    - chama FFmpeg;
    - chama MoneyPrinterTurbo;
    - publica no YouTube.
    """
    if not isinstance(content_segment_ids, list):
        raise EpisodeCompositionError(
            "content_segment_ids deve ser uma lista."
        )

    if not content_segment_ids:
        raise EpisodeCompositionError(
            "O Episode precisa possuir pelo menos um Content Segment."
        )

    normalized_ids: list[int] = []

    for content_segment_id in content_segment_ids:
        if (
            not isinstance(content_segment_id, int)
            or isinstance(content_segment_id, bool)
            or content_segment_id <= 0
        ):
            raise EpisodeCompositionError(
                "Todo content_segment_id deve ser um inteiro positivo."
            )

        normalized_ids.append(content_segment_id)

    segments: list[dict[str, Any]] = []

    for content_segment_id in normalized_ids:
        segment = get_content_segment(content_segment_id)

        if segment is None:
            raise EpisodeCompositionError(
                "Content Segment não encontrado: "
                f"{content_segment_id}"
            )

        segments.append(segment)

    total_duration = validate_episode_composition(
        target_duration_seconds=target_duration_seconds,
        min_duration_seconds=min_duration_seconds,
        max_duration_seconds=max_duration_seconds,
        segments=segments,
    )

    episode = create_and_persist_episode(
        title=title,
        target_duration_seconds=target_duration_seconds,
        min_duration_seconds=min_duration_seconds,
        max_duration_seconds=max_duration_seconds,
        status=status,
    )

    episode_id = episode["id"]

    episode_segments: list[dict[str, Any]] = []

    start_offset = 0.0

    for order, segment in enumerate(segments):
        episode_segment = create_and_persist_episode_segment(
            episode_id=episode_id,
            content_segment_id=segment["id"],
            order=order,
            start_offset_seconds=start_offset,
            role="content",
        )

        episode_segments.append(episode_segment)

        start_offset += float(
            segment["duration_seconds"]
        )

    return {
        "episode": episode,
        "episode_segments": episode_segments,
        "segment_count": len(episode_segments),
        "duration_seconds": total_duration,
        "duration_valid": is_episode_duration_valid(
            episode,
            total_duration,
        ),
        "status": "composed",
    }
