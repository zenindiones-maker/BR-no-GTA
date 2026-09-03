from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.content_unit_service import (
    ContentUnitError,
    validate_content_unit,
)
from app.services.media_format_service import (
    MediaFormatError,
    get_media_format,
)


class ContentSegmentError(ValueError):
    """Erro de validação de segmento audiovisual."""


@dataclass(frozen=True)
class ContentSegment:
    """
    Segmento audiovisual posicionável em uma montagem.

    O Segment não é uma nova peça editorial.
    Ele representa como uma Content Unit será utilizada
    dentro de uma montagem ou derivado.

    source_start_seconds / source_end_seconds permitem cortes
    sem alterar a Content Unit original.
    """

    content_unit_id: int
    order: int
    duration_seconds: float
    media_format: str
    source_start_seconds: float
    source_end_seconds: float
    role: str = "content"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.content_unit_id, int)
            or isinstance(self.content_unit_id, bool)
            or self.content_unit_id <= 0
        ):
            raise ContentSegmentError(
                "content_unit_id deve ser um inteiro positivo."
            )

        if (
            not isinstance(self.order, int)
            or isinstance(self.order, bool)
            or self.order < 0
        ):
            raise ContentSegmentError(
                "order deve ser um inteiro maior ou igual a zero."
            )

        if self.duration_seconds <= 0:
            raise ContentSegmentError(
                "A duração do Segment deve ser positiva."
            )

        if self.source_start_seconds < 0:
            raise ContentSegmentError(
                "source_start_seconds não pode ser negativo."
            )

        if self.source_end_seconds <= self.source_start_seconds:
            raise ContentSegmentError(
                "source_end_seconds deve ser maior que "
                "source_start_seconds."
            )

        source_duration = (
            self.source_end_seconds - self.source_start_seconds
        )

        if self.duration_seconds > source_duration:
            raise ContentSegmentError(
                "A duração do Segment não pode exceder "
                "a duração do trecho de origem."
            )

        if not isinstance(self.role, str) or not self.role.strip():
            raise ContentSegmentError(
                "role deve ser uma string não vazia."
            )

        try:
            get_media_format(self.media_format)
        except MediaFormatError as exc:
            raise ContentSegmentError(str(exc)) from exc


def create_content_segment(
    *,
    content_unit_id: int,
    order: int,
    duration_seconds: float,
    media_format: str,
    source_start_seconds: float,
    source_end_seconds: float,
    role: str = "content",
) -> dict[str, Any]:
    """
    Cria um Segment puramente declarativo.

    Não grava no banco.
    Não renderiza.
    Não corta vídeo.
    Não chama FFmpeg.
    Não chama MPT.

    O Segment apenas descreve o trecho que deverá existir
    em uma futura timeline de produção.
    """
    if (
        not isinstance(content_unit_id, int)
        or isinstance(content_unit_id, bool)
    ):
        raise ContentSegmentError(
            "content_unit_id deve ser um inteiro."
        )

    if not isinstance(order, int) or isinstance(order, bool):
        raise ContentSegmentError(
            "order deve ser um inteiro."
        )

    if not isinstance(duration_seconds, (int, float)):
        raise ContentSegmentError(
            "duration_seconds deve ser numérico."
        )

    if isinstance(duration_seconds, bool):
        raise ContentSegmentError(
            "duration_seconds deve ser numérico."
        )

    if not isinstance(media_format, str):
        raise ContentSegmentError(
            "media_format deve ser uma string."
        )

    if not isinstance(
        source_start_seconds,
        (int, float),
    ) or isinstance(source_start_seconds, bool):
        raise ContentSegmentError(
            "source_start_seconds deve ser numérico."
        )

    if not isinstance(
        source_end_seconds,
        (int, float),
    ) or isinstance(source_end_seconds, bool):
        raise ContentSegmentError(
            "source_end_seconds deve ser numérico."
        )

    if not isinstance(role, str):
        raise ContentSegmentError(
            "role deve ser uma string."
        )

    segment = ContentSegment(
        content_unit_id=content_unit_id,
        order=order,
        duration_seconds=float(duration_seconds),
        media_format=media_format.strip().lower(),
        source_start_seconds=float(source_start_seconds),
        source_end_seconds=float(source_end_seconds),
        role=role.strip().lower(),
    )

    return {
        "content_unit_id": segment.content_unit_id,
        "order": segment.order,
        "duration_seconds": segment.duration_seconds,
        "media_format": segment.media_format,
        "source_start_seconds": segment.source_start_seconds,
        "source_end_seconds": segment.source_end_seconds,
        "role": segment.role,
        "status": "ready",
    }


def create_segment_from_content_unit(
    content_unit: dict[str, Any],
    *,
    content_unit_id: int,
    order: int,
    media_format: str,
    source_start_seconds: float = 0,
    source_end_seconds: float | None = None,
    duration_seconds: float | None = None,
    role: str = "content",
) -> dict[str, Any]:
    """
    Cria um Segment a partir de uma Content Unit.

    Por padrão utiliza toda a unidade como origem.
    É possível selecionar apenas um trecho da unidade.
    """
    try:
        validate_content_unit(content_unit)
    except ContentUnitError as exc:
        raise ContentSegmentError(str(exc)) from exc

    unit_duration = float(
        content_unit["duration_seconds"]
    )

    if source_end_seconds is None:
        source_end_seconds = unit_duration

    source_start = float(source_start_seconds)
    source_end = float(source_end_seconds)

    source_duration = source_end - source_start

    if duration_seconds is None:
        duration_seconds = source_duration

    return create_content_segment(
        content_unit_id=content_unit_id,
        order=order,
        duration_seconds=duration_seconds,
        media_format=media_format,
        source_start_seconds=source_start,
        source_end_seconds=source_end,
        role=role,
    )


def validate_content_segment(
    segment: dict[str, Any],
) -> None:
    """Valida um Segment já materializado em dicionário."""
    if not isinstance(segment, dict) or not segment:
        raise ContentSegmentError(
            "O Segment informado é inválido."
        )

    required_fields = (
        "content_unit_id",
        "order",
        "duration_seconds",
        "media_format",
        "source_start_seconds",
        "source_end_seconds",
        "role",
    )

    missing = [
        field
        for field in required_fields
        if field not in segment
    ]

    if missing:
        raise ContentSegmentError(
            "Segment sem campos obrigatórios: "
            + ", ".join(missing)
        )

    create_content_segment(
        content_unit_id=segment["content_unit_id"],
        order=segment["order"],
        duration_seconds=segment["duration_seconds"],
        media_format=segment["media_format"],
        source_start_seconds=segment["source_start_seconds"],
        source_end_seconds=segment["source_end_seconds"],
        role=segment["role"],
    )
