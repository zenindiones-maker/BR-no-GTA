from __future__ import annotations

from typing import Any

from app.services.content_segment_service import (
    create_and_persist_content_segment,
)
from app.services.content_unit_service import (
    create_and_persist_content_unit,
)


class MediaSelectionError(ValueError):
    """Erro na seleção editorial de mídia."""


def _as_float(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MediaSelectionError(
            f"{field} precisa ser numérico."
        )
    return float(value)


def _extract_candidate_windows(
    knowledge: dict[str, Any],
) -> list[dict[str, float]]:
    """
    Converte cenas do MediaKnowledge em janelas candidatas.

    A seleção inicial usa cenas detectadas pelo PySceneDetect.
    Futuramente os scores de áudio, beat, motion e semântica
    podem refinar a ordenação sem alterar o contrato.
    """
    scenes = knowledge.get("scenes")

    if not isinstance(scenes, list):
        raise MediaSelectionError(
            "MediaKnowledge não possui uma lista de cenas."
        )

    candidates: list[dict[str, float]] = []

    for scene in scenes:
        if not isinstance(scene, dict):
            continue

        start = _as_float(
            scene.get("start_seconds"),
            "scene.start_seconds",
        )
        end = _as_float(
            scene.get("end_seconds"),
            "scene.end_seconds",
        )

        if end <= start:
            continue

        candidates.append(
            {
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": end - start,
            }
        )

    return candidates


def select_media_segments(
    *,
    knowledge: dict[str, Any],
    content_item_id: int,
    script_id: int,
    idea_id: int,
    title: str,
    objective: str,
    hook: str,
    narration: str,
    media_format: str = "video",
    unit_type: str = "segment",
    target_duration_seconds: float = 30.0,
    max_segments: int = 8,
) -> dict[str, Any]:
    """
    Transforma MediaKnowledge em Content Units + Content Segments.

    Não baixa mídia.
    Não corta arquivos.
    Não executa FFmpeg.
    Não renderiza.

    Apenas materializa a decisão editorial de quais trechos
    serão utilizados posteriormente pela montagem.
    """

    if not isinstance(knowledge, dict) or not knowledge:
        raise MediaSelectionError(
            "MediaKnowledge inválido."
        )

    if content_item_id <= 0:
        raise MediaSelectionError(
            "content_item_id inválido."
        )

    if script_id <= 0:
        raise MediaSelectionError(
            "script_id inválido."
        )

    if idea_id <= 0:
        raise MediaSelectionError(
            "idea_id inválido."
        )

    if target_duration_seconds <= 0:
        raise MediaSelectionError(
            "target_duration_seconds deve ser positivo."
        )

    if max_segments <= 0:
        raise MediaSelectionError(
            "max_segments deve ser positivo."
        )

    source_path = knowledge.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        raise MediaSelectionError(
            "MediaKnowledge não possui um source_path válido."
        )

    candidates = _extract_candidate_windows(
        knowledge
    )

    if not candidates:
        raise MediaSelectionError(
            "MediaKnowledge não possui nenhuma cena utilizável."
        )

    selected: list[dict[str, float]] = []
    remaining = float(target_duration_seconds)

    for candidate in candidates:
        if len(selected) >= max_segments:
            break

        duration = candidate["duration_seconds"]

        if remaining <= 0:
            break

        selected_duration = min(
            duration,
            remaining,
        )

        if selected_duration <= 0:
            continue

        selected.append(
            {
                "start_seconds": candidate["start_seconds"],
                "end_seconds": (
                    candidate["start_seconds"]
                    + selected_duration
                ),
                "duration_seconds": selected_duration,
            }
        )

        remaining -= selected_duration

    if not selected:
        raise MediaSelectionError(
            "Nenhum trecho pôde ser selecionado."
        )

    unit = create_and_persist_content_unit(
        content_item_id=content_item_id,
        title=title,
        unit_type=unit_type,
        duration_seconds=sum(
            item["duration_seconds"]
            for item in selected
        ),
        media_format=media_format,
        script_id=script_id,
        idea_id=idea_id,
        objective=objective,
        hook=hook,
        narration=narration,
        visual_requirements=[],
        status="ready",
    )

    unit_id = unit["id"]

    segments: list[dict[str, Any]] = []

    for order, item in enumerate(selected):
        segment = create_and_persist_content_segment(
            content_unit_id=unit_id,
            order=order,
            duration_seconds=item["duration_seconds"],
            media_format=media_format,
            source_start_seconds=item["start_seconds"],
            source_end_seconds=item["end_seconds"],
            role="content",
            status="ready",
            file_path=source_path.strip(),
        )

        segments.append(segment)

    return {
        "content_unit": unit,
        "segments": segments,
        "segment_count": len(segments),
        "duration_seconds": sum(
            segment["duration_seconds"]
            for segment in segments
        ),
        "source": "MediaKnowledge",
    }
