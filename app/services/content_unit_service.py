from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.media_format_service import (
    MediaFormatError,
    get_media_format,
)


class ContentUnitError(ValueError):
    """Erro de validação de unidade de conteúdo."""


CONTENT_UNIT_TYPES = {
    "short",
    "reel",
    "segment",
}


@dataclass(frozen=True)
class ContentUnit:
    """
    Unidade audiovisual reutilizável.

    Uma Content Unit representa uma peça narrativa que pode alimentar
    diferentes derivados e, posteriormente, um episódio.
    """

    title: str
    unit_type: str
    duration_seconds: float
    media_format: str
    script_id: int
    idea_id: int
    objective: str
    hook: str
    narration: str
    visual_requirements: list[dict[str, Any]]

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ContentUnitError(
                "O título da Content Unit é obrigatório."
            )

        if self.unit_type not in CONTENT_UNIT_TYPES:
            raise ContentUnitError(
                f"Tipo de Content Unit não suportado: "
                f"{self.unit_type}"
            )

        if self.duration_seconds <= 0:
            raise ContentUnitError(
                "A duração da Content Unit deve ser positiva."
            )

        if self.script_id <= 0:
            raise ContentUnitError(
                "O script_id deve ser positivo."
            )

        if self.idea_id <= 0:
            raise ContentUnitError(
                "O idea_id deve ser positivo."
            )

        try:
            get_media_format(self.media_format)
        except MediaFormatError as exc:
            raise ContentUnitError(str(exc)) from exc


def create_content_unit(
    *,
    title: str,
    unit_type: str,
    duration_seconds: float,
    media_format: str,
    script_id: int,
    idea_id: int,
    objective: str,
    hook: str,
    narration: str,
    visual_requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Cria uma unidade de conteúdo reutilizável.

    Esta função é puramente declarativa:
    não grava no banco, não renderiza e não publica.

    A unidade pode posteriormente gerar múltiplos derivados.
    """
    if not isinstance(title, str):
        raise ContentUnitError("title deve ser uma string.")

    if not isinstance(unit_type, str):
        raise ContentUnitError(
            "unit_type deve ser uma string."
        )

    if not isinstance(duration_seconds, (int, float)):
        raise ContentUnitError(
            "duration_seconds deve ser numérico."
        )

    if isinstance(duration_seconds, bool):
        raise ContentUnitError(
            "duration_seconds deve ser numérico."
        )

    if not isinstance(script_id, int) or isinstance(script_id, bool):
        raise ContentUnitError(
            "script_id deve ser um inteiro."
        )

    if not isinstance(idea_id, int) or isinstance(idea_id, bool):
        raise ContentUnitError(
            "idea_id deve ser um inteiro."
        )

    if not isinstance(objective, str):
        raise ContentUnitError(
            "objective deve ser uma string."
        )

    if not isinstance(hook, str):
        raise ContentUnitError(
            "hook deve ser uma string."
        )

    if not isinstance(narration, str):
        raise ContentUnitError(
            "narration deve ser uma string."
        )

    if visual_requirements is None:
        visual_requirements = []

    if not isinstance(visual_requirements, list):
        raise ContentUnitError(
            "visual_requirements deve ser uma lista."
        )

    unit = ContentUnit(
        title=title.strip(),
        unit_type=unit_type.strip().lower(),
        duration_seconds=float(duration_seconds),
        media_format=media_format,
        script_id=script_id,
        idea_id=idea_id,
        objective=objective.strip(),
        hook=hook.strip(),
        narration=narration.strip(),
        visual_requirements=visual_requirements,
    )

    return {
        "title": unit.title,
        "unit_type": unit.unit_type,
        "duration_seconds": unit.duration_seconds,
        "media_format": unit.media_format,
        "script_id": unit.script_id,
        "idea_id": unit.idea_id,
        "objective": unit.objective,
        "hook": unit.hook,
        "narration": unit.narration,
        "visual_requirements": unit.visual_requirements,
        "status": "ready",
    }


def create_content_unit_from_content_item(
    content_item: dict[str, Any],
    *,
    unit_type: str,
    media_format: str,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """
    Converte um Content Item existente em uma Content Unit.

    O Content Item continua sendo a origem editorial.
    A Content Unit passa a ser a peça audiovisual reutilizável.
    """
    if not isinstance(content_item, dict) or not content_item:
        raise ContentUnitError(
            "O Content Item informado é inválido."
        )

    required_fields = (
        "title",
        "script_id",
        "idea_id",
        "objective",
        "hook",
        "visual_requirements",
    )

    missing = [
        field
        for field in required_fields
        if field not in content_item
    ]

    if missing:
        raise ContentUnitError(
            "Content Item sem campos obrigatórios: "
            + ", ".join(missing)
        )

    selected_duration = (
        content_item.get("estimated_duration_seconds")
        if duration_seconds is None
        else duration_seconds
    )

    if selected_duration is None:
        raise ContentUnitError(
            "A duração da Content Unit não foi informada."
        )

    return create_content_unit(
        title=content_item["title"],
        unit_type=unit_type,
        duration_seconds=selected_duration,
        media_format=media_format,
        script_id=content_item["script_id"],
        idea_id=content_item["idea_id"],
        objective=content_item["objective"],
        hook=content_item["hook"],
        narration=content_item.get("description", ""),
        visual_requirements=content_item["visual_requirements"],
    )


def validate_content_unit(unit: dict[str, Any]) -> None:
    """Valida uma Content Unit já materializada em dicionário."""
    if not isinstance(unit, dict) or not unit:
        raise ContentUnitError(
            "A Content Unit informada é inválida."
        )

    required_fields = (
        "title",
        "unit_type",
        "duration_seconds",
        "media_format",
        "script_id",
        "idea_id",
        "objective",
        "hook",
        "narration",
        "visual_requirements",
    )

    missing = [
        field
        for field in required_fields
        if field not in unit
    ]

    if missing:
        raise ContentUnitError(
            "Content Unit sem campos obrigatórios: "
            + ", ".join(missing)
        )

    create_content_unit(
        title=unit["title"],
        unit_type=unit["unit_type"],
        duration_seconds=unit["duration_seconds"],
        media_format=unit["media_format"],
        script_id=unit["script_id"],
        idea_id=unit["idea_id"],
        objective=unit["objective"],
        hook=unit["hook"],
        narration=unit["narration"],
        visual_requirements=unit["visual_requirements"],
    )
