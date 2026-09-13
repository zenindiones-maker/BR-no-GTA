from __future__ import annotations

from typing import Any

from app.database.production_plan_repository import (
    get_production_plan_by_content_item_id,
    update_production_plan,
)
from app.services.production_media_bridge import (
    bind_selected_segments,
)


def compose_and_persist_production_media(
    *,
    content_item_id: int,
    segment_ids: list[int],
) -> dict[str, Any]:
    """
    Aplica a composição de mídia já selecionada ao ProductionPlan
    persistido e salva o resultado no mesmo registro.

    Não seleciona mídia.
    Não baixa mídia.
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

    if not isinstance(segment_ids, list) or not segment_ids:
        raise ValueError(
            "segment_ids deve ser uma lista não vazia."
        )

    if any(
        not isinstance(segment_id, int)
        or isinstance(segment_id, bool)
        or segment_id <= 0
        for segment_id in segment_ids
    ):
        raise ValueError(
            "Todos os segment_ids devem ser inteiros positivos."
        )

    production_record = get_production_plan_by_content_item_id(
        content_item_id
    )

    if production_record is None:
        raise RuntimeError(
            "ProductionPlan não encontrado para content_item_id="
            f"{content_item_id}."
        )

    production_plan = production_record.get(
        "production_plan"
    )

    if not isinstance(production_plan, dict):
        raise RuntimeError(
            "Registro persistido não contém ProductionPlan válido."
        )

    if production_plan.get("content_item_id") != content_item_id:
        raise RuntimeError(
            "ProductionPlan possui content_item_id incompatível."
        )

    composed_plan = bind_selected_segments(
        production_plan,
        segment_ids,
    )

    persisted = update_production_plan(
        content_item_id=content_item_id,
        production_plan=composed_plan,
    )

    if not persisted:
        raise RuntimeError(
            "ProductionPlan não foi atualizado."
        )

    persisted_record = get_production_plan_by_content_item_id(
        content_item_id
    )

    if persisted_record is None:
        raise RuntimeError(
            "ProductionPlan desapareceu após atualização."
        )

    persisted_plan = persisted_record.get(
        "production_plan"
    )

    if not isinstance(persisted_plan, dict):
        raise RuntimeError(
            "ProductionPlan persistido após atualização é inválido."
        )

    scenes = persisted_plan.get("scenes")

    if not isinstance(scenes, list):
        raise RuntimeError(
            "ProductionPlan persistido não possui cenas válidas."
        )

    persisted_segment_ids = [
        scene.get("segment_id")
        for scene in scenes
        if isinstance(scene, dict)
    ]

    if persisted_segment_ids != segment_ids:
        raise RuntimeError(
            "segment_ids persistidos não correspondem "
            "à composição solicitada."
        )

    return {
        "content_item_id": content_item_id,
        "production_plan_id": persisted_record["id"],
        "segment_ids": persisted_segment_ids,
        "scene_count": len(scenes),
        "status": "composed",
        "production_plan": persisted_plan,
    }
