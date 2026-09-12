from __future__ import annotations

from typing import Any

from app.database.gta6_goal_repository import get_active_gta6_goal
from app.database.production_plan_repository import (
    get_production_plan_by_content_item_id,
)
from app.services.gta6_goal_service import (
    get_artifacts,
    resolve_next_stage,
    update_artifacts,
)
from app.services.render_worker_service import process_next_render_job
from app.services.video_render_service import create_video_and_enqueue_render
from app.services.video_service import create_video_spec


def process_next_production_execution(
    execution_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Avança exatamente um passo real da produção audiovisual.

    VIDEO:
        ProductionPlan -> VideoSpec -> Video + RenderJob

    RENDER:
        RenderJob -> RenderWorker

    Não executa pesquisa, editorial ou publicação.
    """

    goal = get_active_gta6_goal()

    if goal is None:
        return None

    goal_id = goal["goal_id"]

    resolution = resolve_next_stage(
        goal_id=goal_id,
    )

    next_stage = resolution.get("next_stage")

    if next_stage == "VIDEO":
        artifacts = get_artifacts(
            goal_id=goal_id,
        )

        content_item_id = artifacts.get(
            "content_item_id"
        )

        if (
            not isinstance(content_item_id, int)
            or content_item_id <= 0
        ):
            raise RuntimeError(
                "Goal em VIDEO não possui content_item_id válido."
            )

        stored_plan = (
            get_production_plan_by_content_item_id(
                content_item_id
            )
        )

        if stored_plan is None:
            raise RuntimeError(
                "Content Item não possui Production Plan persistido."
            )

        production_plan = stored_plan.get(
            "production_plan"
        )

        if not isinstance(production_plan, dict):
            raise RuntimeError(
                "Production Plan persistido é inválido."
            )

        if not isinstance(execution_context, dict):
            raise RuntimeError(
                "EXECUTION exige contexto de autorização."
            )

        from app.services.production_media_bridge import bind_selected_segments
        production_plan = bind_selected_segments(
            production_plan, [scene.get("segment_id") for scene in production_plan["scenes"]]
        )

        video_spec = create_video_spec(
            production_plan,
            brain_decision=execution_context,
        )

        composed = create_video_and_enqueue_render(
            video_spec
        )

        video = composed["video"]
        render_job = composed["render_job"]

        video_id = video.get("id")
        render_job_id = render_job.get("id")

        if (
            not isinstance(video_id, int)
            or video_id <= 0
        ):
            raise RuntimeError(
                "Video criado não possui id válido."
            )

        if (
            not isinstance(render_job_id, int)
            or render_job_id <= 0
        ):
            raise RuntimeError(
                "Render Job criado não possui id válido."
            )

        update_artifacts(
            goal_id=goal_id,
            video_id=video_id,
            render_job_id=render_job_id,
        )

        return {
            "goal_id": goal_id,
            "stage": "VIDEO",
            "video": video,
            "render_job": render_job,
        }

    if next_stage == "RENDER":
        result = process_next_render_job(
            execution_context=execution_context,
        )

        return {
            "goal_id": goal_id,
            "stage": "RENDER",
            "result": result,
        }

    return {
        "goal_id": goal_id,
        "stage": next_stage,
        "status": "nothing_to_execute",
    }
