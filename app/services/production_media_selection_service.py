from __future__ import annotations

from typing import Any

from app.database.content_repository import get_content_item
from app.database.media_knowledge_repository import (
    MediaKnowledgeRepository,
)
from app.database.production_plan_repository import (
    get_production_plan_by_content_item_id,
)
from app.services.media_selection_service import (
    select_media_segments,
)


def select_production_media(
    *,
    content_item_id: int,
    knowledge_id: int,
) -> dict[str, Any]:
    """
    Materializa exatamente um ContentSegment para cada cena
    do ProductionPlan.

    Cada segmento possui a mesma duração da cena correspondente,
    satisfazendo o contrato de production_media_bridge.

    Não baixa mídia.
    Não executa análise.
    Não altera o ProductionPlan.
    Não renderiza.
    """

    if (
        not isinstance(content_item_id, int)
        or isinstance(content_item_id, bool)
        or content_item_id <= 0
    ):
        raise ValueError(
            "content_item_id deve ser um inteiro positivo."
        )

    if (
        not isinstance(knowledge_id, int)
        or isinstance(knowledge_id, bool)
        or knowledge_id <= 0
    ):
        raise ValueError(
            "knowledge_id deve ser um inteiro positivo."
        )

    production_record = get_production_plan_by_content_item_id(
        content_item_id
    )

    if production_record is None:
        raise RuntimeError(
            "ProductionPlan não encontrado para content_item_id="
            f"{content_item_id}."
        )

    production_plan = production_record.get("production_plan")

    if not isinstance(production_plan, dict):
        raise RuntimeError(
            "Registro persistido não contém ProductionPlan válido."
        )

    if production_plan.get("content_item_id") != content_item_id:
        raise RuntimeError(
            "ProductionPlan possui content_item_id incompatível."
        )

    script_id = production_plan.get("script_id")
    idea_id = production_plan.get("idea_id")
    objective = production_plan.get("objective")

    if (
        not isinstance(script_id, int)
        or isinstance(script_id, bool)
        or script_id <= 0
    ):
        raise RuntimeError(
            "ProductionPlan não possui script_id válido."
        )

    if (
        not isinstance(idea_id, int)
        or isinstance(idea_id, bool)
        or idea_id <= 0
    ):
        raise RuntimeError(
            "ProductionPlan não possui idea_id válido."
        )

    if not isinstance(objective, str) or not objective.strip():
        raise RuntimeError(
            "ProductionPlan não possui objective válido."
        )

    scenes = production_plan.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise RuntimeError(
            "ProductionPlan não possui cenas válidas."
        )

    content_item = get_content_item(content_item_id)

    if content_item is None:
        raise RuntimeError(
            f"ContentItem não encontrado: {content_item_id}."
        )

    title = content_item.get("title")

    if not isinstance(title, str) or not title.strip():
        raise RuntimeError(
            "ContentItem não possui título válido."
        )

    repository = MediaKnowledgeRepository()
    knowledge = repository.get_payload(knowledge_id)

    if not isinstance(knowledge, dict) or not knowledge:
        raise RuntimeError(
            f"MediaKnowledge não encontrado: {knowledge_id}."
        )

    segment_ids: list[int] = []
    content_unit_ids: list[int] = []
    selections: list[dict[str, Any]] = []
    source_cursor_seconds: float | None = None

    for scene_index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise RuntimeError(
                f"Cena inválida na posição {scene_index}."
            )

        duration = scene.get("duration_seconds")

        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration <= 0
        ):
            raise RuntimeError(
                f"Cena {scene_index} possui duração inválida."
            )

        narration = scene.get("narration")

        if (
            not isinstance(narration, str)
            or not narration.strip()
        ):
            raise RuntimeError(
                f"Cena {scene_index} não possui narração válida."
            )

        narrative_block = scene.get("narrative_block")

        scene_title = (
            narrative_block.strip()
            if isinstance(narrative_block, str)
            and narrative_block.strip()
            else f"{title.strip()} — Cena {scene_index}"
        )

        selection = select_media_segments(
            knowledge=knowledge,
            content_item_id=content_item_id,
            script_id=script_id,
            idea_id=idea_id,
            title=scene_title,
            objective=objective.strip(),
            hook=narration.strip(),
            narration=narration.strip(),
            media_format="landscape_16_9",
            target_duration_seconds=float(duration),
            max_segments=1,
            source_cursor_seconds=source_cursor_seconds,
            continuous_window=True,
        )

        segments = selection.get("segments")

        if not isinstance(segments, list) or len(segments) != 1:
            raise RuntimeError(
                f"Cena {scene_index} precisa produzir exatamente "
                "um ContentSegment."
            )

        segment = segments[0]
        segment_id = segment.get("id")
        segment_duration = segment.get("duration_seconds")
        source_end_seconds = segment.get(
            "source_end_seconds"
        )

        if (
            not isinstance(segment_id, int)
            or isinstance(segment_id, bool)
            or segment_id <= 0
        ):
            raise RuntimeError(
                f"Cena {scene_index} não produziu segment_id válido."
            )

        if (
            not isinstance(segment_duration, (int, float))
            or isinstance(segment_duration, bool)
            or abs(float(segment_duration) - float(duration)) > 0.001
        ):
            raise RuntimeError(
                f"Cena {scene_index}: duração do segmento "
                "não corresponde à duração da cena."
            )

        if (
            not isinstance(source_end_seconds, (int, float))
            or isinstance(source_end_seconds, bool)
            or source_end_seconds <= 0
        ):
            raise RuntimeError(
                f"Cena {scene_index} não produziu "
                "source_end_seconds válido."
            )

        source_cursor_seconds = float(
            source_end_seconds
        )

        content_unit = selection.get("content_unit")

        if not isinstance(content_unit, dict):
            raise RuntimeError(
                f"Cena {scene_index} não produziu ContentUnit."
            )

        content_unit_id = content_unit.get("id")

        if (
            not isinstance(content_unit_id, int)
            or isinstance(content_unit_id, bool)
            or content_unit_id <= 0
        ):
            raise RuntimeError(
                f"Cena {scene_index} não produziu "
                "content_unit_id válido."
            )

        segment_ids.append(segment_id)
        content_unit_ids.append(content_unit_id)

        selections.append(
            {
                "scene_order": scene.get(
                    "order",
                    scene_index,
                ),
                "content_unit_id": content_unit_id,
                "segment_id": segment_id,
                "duration_seconds": float(
                    segment_duration
                ),
                "asset_ref": selection.get("asset_ref"),
                "source_url": selection.get("source_url"),
            }
        )

    if len(segment_ids) != len(scenes):
        raise RuntimeError(
            "A composição não produziu exatamente um "
            "segment_id por cena."
        )

    return {
        "content_item_id": content_item_id,
        "knowledge_id": knowledge_id,
        "content_unit_ids": content_unit_ids,
        "segment_ids": segment_ids,
        "scene_count": len(scenes),
        "selections": selections,
        "status": "selected",
    }
