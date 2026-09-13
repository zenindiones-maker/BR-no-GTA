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
    source_cursor_seconds: float | None = None,
    continuous_window: bool = False,
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

    if source_cursor_seconds is not None:
        if (
            not isinstance(source_cursor_seconds, (int, float))
            or isinstance(source_cursor_seconds, bool)
            or source_cursor_seconds < 0
        ):
            raise MediaSelectionError(
                "source_cursor_seconds deve ser não negativo."
            )

        source_cursor_seconds = float(source_cursor_seconds)

    source_path = knowledge.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        raise MediaSelectionError(
            "MediaKnowledge não possui um source_path válido."
        )

    metadata = knowledge.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise MediaSelectionError(
            "MediaKnowledge possui metadata inválido."
        )

    source_url = metadata.get("source_url")
    if source_url is not None:
        if not isinstance(source_url, str) or not source_url.strip():
            raise MediaSelectionError(
                "MediaKnowledge possui source_url inválido."
            )
        source_url = source_url.strip()

    asset_ref = source_path.strip()

    candidates = _extract_candidate_windows(
        knowledge
    )

    if not candidates:
        raise MediaSelectionError(
            "MediaKnowledge não possui nenhuma cena utilizável."
        )

    selected: list[dict[str, float]] = []
    remaining = float(target_duration_seconds)

    if continuous_window:
        if not isinstance(continuous_window, bool):
            raise MediaSelectionError(
                "continuous_window deve ser booleano."
            )

        cursor = (
            float(source_cursor_seconds)
            if source_cursor_seconds is not None
            else candidates[0]["start_seconds"]
        )
        window_start = cursor
        window_end = window_start + float(target_duration_seconds)

        coverage_cursor = window_start

        for candidate in candidates:
            candidate_start = candidate["start_seconds"]
            candidate_end = candidate["end_seconds"]

            if candidate_end <= coverage_cursor:
                continue

            if candidate_start > coverage_cursor + 0.001:
                break

            coverage_cursor = max(
                coverage_cursor,
                candidate_end,
            )

            if coverage_cursor + 0.001 >= window_end:
                break

        if coverage_cursor + 0.001 < window_end:
            raise MediaSelectionError(
                "Mídia disponível insuficiente para atingir "
                "target_duration_seconds sem reutilização."
            )

        selected = [
            {
                "start_seconds": window_start,
                "end_seconds": window_end,
                "duration_seconds": float(
                    target_duration_seconds
                ),
            }
        ]
        remaining = 0.0

    else:
        for candidate in candidates:
            if len(selected) >= max_segments:
                break

            if remaining <= 0:
                break

            candidate_start = candidate["start_seconds"]
            candidate_end = candidate["end_seconds"]

            if source_cursor_seconds is not None:
                if candidate_end <= source_cursor_seconds:
                    continue

                candidate_start = max(
                    candidate_start,
                    source_cursor_seconds,
                )

            available_duration = (
                candidate_end - candidate_start
            )

            if available_duration <= 0:
                continue

            if (
                max_segments == 1
                and available_duration + 0.001 < remaining
            ):
                continue

            selected_duration = min(
                available_duration,
                remaining,
            )

            if selected_duration <= 0:
                continue

            selected.append(
                {
                    "start_seconds": candidate_start,
                    "end_seconds": (
                        candidate_start
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

    if remaining > 0.001:
        raise MediaSelectionError(
            "Mídia disponível insuficiente para atingir "
            "target_duration_seconds sem reutilização."
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
            asset_ref=asset_ref,
            source_url=source_url,
        )

        segment = dict(segment)
        segment["asset_ref"] = asset_ref
        segment["source_url"] = source_url

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
        "asset_ref": asset_ref,
        "source_url": source_url,
    }
