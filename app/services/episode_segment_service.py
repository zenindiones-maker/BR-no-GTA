from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class EpisodeSegmentError(ValueError):
    """Erro de validação de segmento de episódio."""


@dataclass(frozen=True)
class EpisodeSegment:
    """
    Uso de um Content Segment dentro de um Episode.

    Esta entidade NÃO duplica o Content Segment.
    Ela representa apenas a relação de montagem.
    """

    episode_id: int
    content_segment_id: int
    order: int
    start_offset_seconds: float = 0.0
    role: str = "content"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.episode_id, int)
            or isinstance(self.episode_id, bool)
            or self.episode_id <= 0
        ):
            raise EpisodeSegmentError(
                "episode_id deve ser um inteiro positivo."
            )

        if (
            not isinstance(self.content_segment_id, int)
            or isinstance(self.content_segment_id, bool)
            or self.content_segment_id <= 0
        ):
            raise EpisodeSegmentError(
                "content_segment_id deve ser um inteiro positivo."
            )

        if (
            not isinstance(self.order, int)
            or isinstance(self.order, bool)
            or self.order < 0
        ):
            raise EpisodeSegmentError(
                "order deve ser um inteiro maior ou igual a zero."
            )

        if (
            not isinstance(self.start_offset_seconds, (int, float))
            or isinstance(self.start_offset_seconds, bool)
            or self.start_offset_seconds < 0
        ):
            raise EpisodeSegmentError(
                "start_offset_seconds deve ser não negativo."
            )

        if not isinstance(self.role, str) or not self.role.strip():
            raise EpisodeSegmentError(
                "role deve ser uma string não vazia."
            )


def create_episode_segment(
    *,
    episode_id: int,
    content_segment_id: int,
    order: int,
    start_offset_seconds: float = 0.0,
    role: str = "content",
) -> dict[str, Any]:
    """
    Cria uma relação entre Episode e Content Segment.

    Não altera o Content Segment original.
    Não renderiza.
    Não executa FFmpeg/MPT.
    """
    segment = EpisodeSegment(
        episode_id=episode_id,
        content_segment_id=content_segment_id,
        order=order,
        start_offset_seconds=float(start_offset_seconds),
        role=role.strip(),
    )

    return {
        "episode_id": segment.episode_id,
        "content_segment_id": segment.content_segment_id,
        "order": segment.order,
        "start_offset_seconds": segment.start_offset_seconds,
        "role": segment.role,
        "status": "ready",
    }


def validate_episode_segment(
    segment: dict[str, Any],
) -> dict[str, Any]:
    """Valida novamente um Episode Segment materializado."""
    if not isinstance(segment, dict) or not segment:
        raise EpisodeSegmentError(
            "O Episode Segment informado é inválido."
        )

    required_fields = (
        "episode_id",
        "content_segment_id",
        "order",
        "start_offset_seconds",
        "role",
    )

    missing = [
        field
        for field in required_fields
        if field not in segment
    ]

    if missing:
        raise EpisodeSegmentError(
            "Episode Segment sem campos obrigatórios: "
            + ", ".join(missing)
        )

    return create_episode_segment(
        episode_id=segment["episode_id"],
        content_segment_id=segment["content_segment_id"],
        order=segment["order"],
        start_offset_seconds=segment[
            "start_offset_seconds"
        ],
        role=segment["role"],
    )

from app.database.episode_segment_repository import (
    insert_episode_segment,
    get_episode_segment,
)


def create_and_persist_episode_segment(
    *,
    episode_id: int,
    content_segment_id: int,
    order: int,
    start_offset_seconds: float = 0.0,
    role: str = "content",
    status: str = "ready",
) -> dict[str, Any]:
    """
    Cria um Episode Segment, valida o domínio e persiste o registro.

    O Episode Segment representa a utilização de um
    Content Segment dentro de um Episode.

    O service permanece responsável por:
    - validação;
    - regras do domínio;
    - normalização.

    O repository permanece responsável pelo SQLite.

    Esta função não:
    - renderiza;
    - corta vídeo;
    - chama FFmpeg;
    - chama MoneyPrinterTurbo;
    - publica no YouTube.
    """
    segment = create_episode_segment(
        episode_id=episode_id,
        content_segment_id=content_segment_id,
        order=order,
        start_offset_seconds=start_offset_seconds,
        role=role,
    )

    episode_segment_id = insert_episode_segment(
        episode_id=segment["episode_id"],
        content_segment_id=segment["content_segment_id"],
        episode_order=segment["order"],
        start_offset_seconds=segment[
            "start_offset_seconds"
        ],
        role=segment["role"],
    )

    persisted = get_episode_segment(episode_segment_id)

    if persisted is None:
        raise RuntimeError(
            "Episode Segment não foi encontrado após persistência: "
            f"{episode_segment_id}"
        )

    return persisted
