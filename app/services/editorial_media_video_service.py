from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.editorial_media_bridge import (
    EditorialMediaBridge,
    EditorialMediaBridgeError,
)
from app.services.media_selection_service import select_media_segments
from app.services.video_service import create_video_spec


class EditorialMediaVideoError(RuntimeError):
    """Erro na composição editorial + mídia + vídeo."""


def build_video_spec_from_editorial_media(
    *,
    idea_id: int,
    content_item: dict[str, Any],
    production_plan: dict[str, Any],
    output_path: Path,
    brain_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Conecta o pipeline editorial à mídia real.

    Fluxo:

        Idea
          ↓
        ResearchItem
          ↓
        source_url
          ↓
        Media Ingestion
          ↓
        arquivo físico
          ↓
        Media Worker
          ↓
        MediaKnowledge
          ↓
        Media Selection
          ↓
        cenas com file_path
          ↓
        Video Spec
          ↓
        VEDIT
    """
    if not isinstance(content_item, dict) or not content_item:
        raise EditorialMediaVideoError("content_item inválido.")

    if not isinstance(production_plan, dict) or not production_plan:
        raise EditorialMediaVideoError("production_plan inválido.")

    required_content_fields = (
        "id",
        "script_id",
        "idea_id",
        "title",
        "objective",
        "estimated_duration_seconds",
        "narrative_blocks",
    )

    for field in required_content_fields:
        if field not in content_item:
            raise EditorialMediaVideoError(
                f"content_item não possui o campo obrigatório: {field}."
            )

    if int(content_item["idea_id"]) != int(idea_id):
        raise EditorialMediaVideoError(
            "idea_id do content_item não corresponde à ideia informada."
        )

    narrative_blocks = content_item.get("narrative_blocks")

    if not isinstance(narrative_blocks, list) or not narrative_blocks:
        raise EditorialMediaVideoError(
            "content_item precisa possuir narrative_blocks."
        )

    bridge = EditorialMediaBridge()

    try:
        media_result = bridge.prepare_for_idea(
            idea_id=idea_id,
            output_path=output_path,
        )
    except EditorialMediaBridgeError as exc:
        raise EditorialMediaVideoError(str(exc)) from exc

    selection = select_media_segments(
        knowledge=media_result.knowledge,
        content_item_id=int(content_item["id"]),
        script_id=int(content_item["script_id"]),
        idea_id=idea_id,
        title=str(content_item["title"]),
        objective=str(content_item["objective"]),
        hook=str(content_item.get("hook") or ""),
        narration="\n\n".join(
            str(block.get("content") or "").strip()
            for block in narrative_blocks
            if isinstance(block, dict)
            and str(block.get("content") or "").strip()
        ),
        target_duration_seconds=float(
            content_item["estimated_duration_seconds"]
        ),
    )

    selected_segments = selection.get("segments")

    if not isinstance(selected_segments, list) or not selected_segments:
        raise EditorialMediaVideoError(
            "A seleção de mídia não retornou segmentos."
        )

    production_scenes = list(production_plan.get("scenes") or [])

    if not production_scenes:
        raise EditorialMediaVideoError(
            "production_plan precisa possuir cenas."
        )

    media_scenes: list[dict[str, Any]] = []

    for order, segment in enumerate(selected_segments, start=1):
        if not isinstance(segment, dict):
            raise EditorialMediaVideoError(
                f"Segmento de mídia inválido na posição {order}."
            )

        narrative_scene = (
            production_scenes[order - 1]
            if order - 1 < len(production_scenes)
            else {}
        )

        file_path = segment.get("file_path")

        if not file_path:
            raise EditorialMediaVideoError(
                f"Segmento de mídia {order} não possui file_path."
            )

        media_scenes.append(
            {
                "order": order,
                "segment_id": segment["id"],
                "content_unit_id": segment["content_unit_id"],
                "file_path": file_path,
                "source_start_seconds": segment["source_start_seconds"],
                "source_end_seconds": segment["source_end_seconds"],
                "narrative_block": narrative_scene.get(
                    "narrative_block",
                    "",
                ),
                "narration": narrative_scene.get(
                    "narration",
                    "",
                ),
                "visual_type": narrative_scene.get(
                    "visual_type",
                    "gameplay",
                ),
                "visual_description": narrative_scene.get(
                    "visual_description",
                    "",
                ),
                "duration_seconds": segment["duration_seconds"],
                "requirements": list(
                    narrative_scene.get("requirements") or []
                ),
            }
        )

    video_production_plan = dict(production_plan)
    video_production_plan["scenes"] = media_scenes
    video_production_plan["estimated_duration_seconds"] = (
        selection["duration_seconds"]
    )

    video_spec = create_video_spec(
        video_production_plan,
        brain_decision=brain_decision,
    )

    video_spec["media"] = {
        "source_url": media_result.source_url,
        "output_path": media_result.output_path,
        "knowledge_id": media_result.knowledge_id,
        "selection": selection,
    }

    return video_spec
