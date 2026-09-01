from typing import Any


def create_video_spec(
    production_plan: dict[str, Any],
) -> dict[str, Any]:
    """
    Transforma um Production Plan em uma especificação estruturada de vídeo.

    Esta camada não renderiza vídeo.
    Ela define o que deverá ser entregue à futura etapa de execução/renderização.
    """

    if not isinstance(production_plan, dict) or not production_plan:
        raise ValueError("O production plan informado é inválido.")

    required_fields = [
        "content_item_id",
        "script_id",
        "idea_id",
        "objective",
        "format",
        "estimated_duration_seconds",
        "scenes",
        "audio_requirements",
        "visual_requirements",
    ]

    for field in required_fields:
        if field not in production_plan:
            raise ValueError(
                f"O production plan não possui o campo obrigatório: {field}."
            )

    scenes = production_plan.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError(
            "O production plan precisa possuir cenas."
        )

    return {
        "content_item_id": production_plan["content_item_id"],
        "script_id": production_plan["script_id"],
        "idea_id": production_plan["idea_id"],
        "objective": production_plan["objective"],
        "format": production_plan["format"],
        "estimated_duration_seconds": (
            production_plan["estimated_duration_seconds"]
        ),
        "status": "ready",
        "scenes": scenes,
        "audio_requirements": list(
            production_plan.get("audio_requirements") or []
        ),
        "visual_requirements": list(
            production_plan.get("visual_requirements") or []
        ),
    }
