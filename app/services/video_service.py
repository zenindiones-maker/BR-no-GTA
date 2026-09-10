from typing import Any

from app.database.video_repository import insert_video
from app.services.vedit_service import (
    apply_edit_plan_to_video_spec,
    build_brain_context,
    create_edit_plan,
)


def create_video_spec(
    production_plan: dict[str, Any],
    *,
    brain_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Transforma um Production Plan em uma especificação estruturada de vídeo.

    Esta camada não persiste nem renderiza vídeo.
    Ela define o contrato de entrada da etapa Video.
    """

    if not isinstance(production_plan, dict) or not production_plan:
        raise ValueError(
            "O production plan informado é inválido."
        )

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

    video_spec = {
        "content_item_id": production_plan["content_item_id"],
        "script_id": production_plan["script_id"],
        "idea_id": production_plan["idea_id"],
        "objective": production_plan["objective"],
        "format": production_plan["format"],
        "estimated_duration_seconds": (
            production_plan["estimated_duration_seconds"]
        ),
        "status": "ready",
        "title": production_plan.get("title"),
        "scenes": scenes,
        "audio_requirements": list(
            production_plan.get("audio_requirements") or []
        ),
        "visual_requirements": list(
            production_plan.get("visual_requirements") or []
        ),
    }

    decision = brain_decision or {}

    # Contexto de execução: atravessa o Video Spec intacto
    # até o Render Job / MPT. Não pertence ao Brain nem ao VEDIT.
    for field in (
        "brain_decision_id",
        "execution_id",
        "authorized_action",
    ):
        if field in decision:
            video_spec[field] = decision[field]

    normalized_brain_context = build_brain_context(
        action=decision.get("action", "EXECUTION"),
        reason=decision.get(
            "reason",
            "Execução audiovisual autorizada pelo GTA6 Brain.",
        ),
        priority=decision.get("priority", "MEDIUM"),
        confidence=float(
            decision.get("confidence", 1.0)
        ),
    )

    edit_plan = create_edit_plan(
        production_plan=production_plan,
        brain_decision=normalized_brain_context,
    )

    return apply_edit_plan_to_video_spec(
        video_spec=video_spec,
        edit_plan=edit_plan,
    )


def _build_video_title(
    video_spec: dict[str, Any],
) -> str:
    title = video_spec.get("title")

    if isinstance(title, str) and title.strip():
        return title.strip()

    return f"Vídeo do Content Item {video_spec['content_item_id']}"


def create_video(
    video_spec: dict[str, Any],
) -> dict[str, Any]:
    """
    Cria e persiste um Video a partir de uma Video Spec.

    Esta camada representa o produto audiovisual.
    Ela não executa, renderiza ou cria Render Jobs.
    """

    if not isinstance(video_spec, dict) or not video_spec:
        raise ValueError(
            "O video spec informado é inválido."
        )

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
        if field not in video_spec:
            raise ValueError(
                "O video spec não possui o campo obrigatório: "
                f"{field}."
            )

    scenes = video_spec.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError(
            "O video spec precisa possuir cenas."
        )

    title = _build_video_title(video_spec)

    video_id = insert_video(
        content_item_id=int(video_spec["content_item_id"]),
        title=title,
        status="draft",
    )

    return {
        "id": video_id,
        "content_item_id": video_spec["content_item_id"],
        "script_id": video_spec["script_id"],
        "idea_id": video_spec["idea_id"],
        "title": title,
        "objective": video_spec["objective"],
        "format": video_spec["format"],
        "estimated_duration_seconds": (
            video_spec["estimated_duration_seconds"]
        ),
        "status": "draft",
        "file_path": None,
        "scenes": video_spec["scenes"],
        "audio_requirements": list(
            video_spec.get("audio_requirements") or []
        ),
        "visual_requirements": list(
            video_spec.get("visual_requirements") or []
        ),
        "render": dict(video_spec.get("render") or {}),
    }
