from __future__ import annotations

from typing import Any

from app.database.gta6_goal_repository import (
    get_gta6_goal_artifacts,
)
from app.database.production_plan_repository import (
    get_production_plan_by_content_item_id,
)
from app.database.render_queue_repository import (
    get_render_job,
)
from app.database.video_repository import (
    get_video,
)
from app.services.gta6_goal_service import (
    update_artifacts,
)
from app.services.production_media_bridge import (
    bind_selected_segments,
)
from app.services.render_queue_service import (
    enqueue_video_render,
)
from app.services.video_execution_service import (
    create_video_execution_spec,
)
from app.services.video_service import (
    create_video_spec,
)


_REQUIRED_EXECUTION_FIELDS = (
    "brain_decision_id",
    "execution_id",
    "authorized_action",
)


def _validate_execution_context(
    execution_context: dict[str, Any] | None,
) -> dict[str, str]:
    if not isinstance(execution_context, dict):
        raise ValueError(
            "Render recovery exige contexto de autorização do Harness."
        )

    normalized: dict[str, str] = {}

    for field in _REQUIRED_EXECUTION_FIELDS:
        value = execution_context.get(field)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "Render recovery exige autorização completa: "
                f"{field}."
            )

        normalized[field] = value.strip()

    if normalized["authorized_action"] != "EXECUTION":
        raise ValueError(
            "Render recovery só pode ser criada para "
            "authorized_action=EXECUTION."
        )

    return normalized


def recover_failed_render_job(
    *,
    goal_id: str,
    failed_render_job_id: int,
    execution_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Cria uma nova unidade RenderJob queued a partir de um RenderJob failed.

    Esta boundary:
    - não reabre o job falho;
    - não cria outro Video;
    - não executa render;
    - não reutiliza autorização antiga;
    - não copia edit_plan legado;
    - reconstitui mídia/lineage a partir da persistência vigente.
    """

    authorization = _validate_execution_context(
        execution_context,
    )

    if (
        not isinstance(failed_render_job_id, int)
        or isinstance(failed_render_job_id, bool)
        or failed_render_job_id <= 0
    ):
        raise ValueError(
            "failed_render_job_id deve ser um inteiro positivo."
        )

    failed_job = get_render_job(
        failed_render_job_id,
    )

    if failed_job is None:
        raise ValueError(
            f"Render job não encontrado: {failed_render_job_id}"
        )

    if failed_job.get("status") != "failed":
        raise ValueError(
            "Render recovery exige RenderJob em estado failed."
        )

    old_brain_decision_id = failed_job.get(
        "brain_decision_id"
    )
    old_execution_id = failed_job.get(
        "execution_id"
    )

    if (
        authorization["brain_decision_id"]
        == old_brain_decision_id
    ):
        raise ValueError(
            "Render recovery exige novo brain_decision_id."
        )

    if (
        authorization["execution_id"]
        == old_execution_id
    ):
        raise ValueError(
            "Render recovery exige novo execution_id."
        )

    video_id = failed_job.get("video_id")

    if (
        not isinstance(video_id, int)
        or isinstance(video_id, bool)
        or video_id <= 0
    ):
        raise ValueError(
            "RenderJob failed não possui video_id válido."
        )

    video = get_video(video_id)

    if video is None:
        raise ValueError(
            f"Video não encontrado: {video_id}"
        )

    artifacts = get_gta6_goal_artifacts(
        goal_id,
    )

    if artifacts is None:
        raise ValueError(
            f"Goal não possui artifacts persistidos: {goal_id}"
        )

    if artifacts.get("render_job_id") != failed_render_job_id:
        raise ValueError(
            "Goal não referencia o RenderJob failed informado."
        )

    if artifacts.get("video_id") != video_id:
        raise ValueError(
            "Goal e RenderJob não referenciam o mesmo Video."
        )

    content_item_id = artifacts.get(
        "content_item_id"
    )
    script_id = artifacts.get(
        "script_id"
    )
    idea_id = artifacts.get(
        "idea_id"
    )

    if video.get("content_item_id") != content_item_id:
        raise ValueError(
            "Video e Goal possuem content_item_id divergente."
        )

    if failed_job.get("content_item_id") != content_item_id:
        raise ValueError(
            "RenderJob e Goal possuem content_item_id divergente."
        )

    if failed_job.get("script_id") != script_id:
        raise ValueError(
            "RenderJob e Goal possuem script_id divergente."
        )

    if failed_job.get("idea_id") != idea_id:
        raise ValueError(
            "RenderJob e Goal possuem idea_id divergente."
        )

    if (
        not isinstance(content_item_id, int)
        or content_item_id <= 0
    ):
        raise ValueError(
            "Goal não possui content_item_id válido."
        )

    stored_plan = get_production_plan_by_content_item_id(
        content_item_id,
    )

    if stored_plan is None:
        raise ValueError(
            "Content Item não possui Production Plan persistido."
        )

    production_plan = stored_plan.get(
        "production_plan"
    )

    if not isinstance(production_plan, dict):
        raise ValueError(
            "Production Plan persistido é inválido."
        )

    if production_plan.get("script_id") != script_id:
        raise ValueError(
            "ProductionPlan e Goal possuem script_id divergente."
        )

    if production_plan.get("idea_id") != idea_id:
        raise ValueError(
            "ProductionPlan e Goal possuem idea_id divergente."
        )

    scenes = production_plan.get("scenes")

    if not isinstance(scenes, list) or not scenes:
        raise ValueError(
            "Production Plan não possui cenas válidas."
        )

    segment_ids = [
        scene.get("segment_id")
        for scene in scenes
    ]

    rebound_plan = bind_selected_segments(
        production_plan,
        segment_ids,
    )

    if "edit_plan" in rebound_plan:
        rebound_plan = dict(rebound_plan)
        rebound_plan.pop("edit_plan", None)

    video_spec = create_video_spec(
        rebound_plan,
        brain_decision=authorization,
    )

    video_spec.pop("edit_plan", None)

    video_execution_spec = create_video_execution_spec(
        video_spec,
    )

    video_execution_spec.pop(
        "edit_plan",
        None,
    )

    new_render_job_id = enqueue_video_render(
        video_execution_spec,
        video_id=video_id,
    )

    new_render_job = get_render_job(
        new_render_job_id,
    )

    if new_render_job is None:
        raise RuntimeError(
            "Novo RenderJob não foi encontrado após recovery."
        )

    if new_render_job.get("status") != "queued":
        raise RuntimeError(
            "Novo RenderJob de recovery não ficou queued."
        )

    if new_render_job.get("video_id") != video_id:
        raise RuntimeError(
            "Novo RenderJob não preservou o Video existente."
        )

    update_artifacts(
        goal_id=goal_id,
        video_id=video_id,
        render_job_id=new_render_job_id,
    )

    return {
        "authority": "deepseek_harness",
        "authorized_action": authorization["authorized_action"],
        "brain_decision_id": authorization["brain_decision_id"],
        "execution_id": authorization["execution_id"],
        "goal_id": goal_id,
        "failed_render_job_id": failed_render_job_id,
        "video_id": video_id,
        "new_render_job_id": new_render_job_id,
        "status": "queued",
        "render_job": new_render_job,
    }
