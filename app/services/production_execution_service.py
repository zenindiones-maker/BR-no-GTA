from __future__ import annotations

from typing import Any

from app.database.gta6_goal_repository import get_active_gta6_goal, get_gta6_goal
from app.database.production_plan_repository import get_production_plan_by_content_item_id
from app.services.gta6_goal_service import get_artifacts, resolve_next_stage, update_artifacts
from app.services.render_worker_service import process_next_render_job, process_render_job
from app.services.video_render_service import create_video_and_enqueue_render
from app.services.video_service import create_video_spec
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.production_media_composition_service import (
    PRODUCTION_MEDIA_CAPABILITY_ID,
    PRODUCTION_MEDIA_EXECUTOR_BINDING,
    compose_and_persist_production_media,
)
from app.services.production_brand_asset_service import (
    PRODUCTION_BRAND_ASSET_CAPABILITY_ID,
    PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING,
    bind_active_brand_assets,
)


def _govern_production_media_binding(
    *,
    parent_authorization,
    production_plan: dict[str, Any],
) -> dict[str, Any]:
    """Derive the bounded Production->Media decision from the persisted Harness action authorization."""
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="production media selected segment binding",
            authorized_action="EXECUTION",
            domain="production-media",
            required_capability_id=PRODUCTION_MEDIA_CAPABILITY_ID,
            required_policy_tags=("production", "media", "binding"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    if routing.selected_capability_id != PRODUCTION_MEDIA_CAPABILITY_ID:
        raise PermissionError("Harness selected an unexpected production media capability")
    if routing.selected_executor_binding != PRODUCTION_MEDIA_EXECUTOR_BINDING:
        raise PermissionError("Harness selected an unexpected production media executor")

    lineage = {
        "parent_authorization_id": parent_authorization.authorization_id,
        "routing_id": routing.routing_id,
        "capability_id": PRODUCTION_MEDIA_CAPABILITY_ID,
        "selected_executor_binding": PRODUCTION_MEDIA_EXECUTOR_BINDING,
        "content_item_id": production_plan.get("content_item_id"),
        "script_id": production_plan.get("script_id"),
        "idea_id": production_plan.get("idea_id"),
    }
    capability_authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{PRODUCTION_MEDIA_CAPABILITY_ID}",
        harness_decision_id=parent_authorization.harness_decision_id,
        execution_id=parent_authorization.execution_id,
        lineage=lineage,
    )
    segment_ids = [scene.get("segment_id") for scene in production_plan.get("scenes", [])]
    return compose_and_persist_production_media(
        content_item_id=production_plan["content_item_id"],
        segment_ids=segment_ids,
        authorization=capability_authorization,
        routing_decision=routing,
        execution_id=parent_authorization.execution_id,
    )


def _govern_brand_asset_binding(
    *,
    parent_authorization,
    content_item_id: int,
) -> dict[str, Any]:
    """Snapshot the currently active verified intro/watermark for one new production execution."""
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="production branding bind active intro watermark assets",
            authorized_action="EXECUTION",
            domain="production-branding",
            required_capability_id=PRODUCTION_BRAND_ASSET_CAPABILITY_ID,
            required_policy_tags=("production", "branding", "binding"),
            provider_required=False,
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    if routing.selected_capability_id != PRODUCTION_BRAND_ASSET_CAPABILITY_ID:
        raise PermissionError("Harness selected an unexpected brand asset capability")
    if routing.selected_executor_binding != PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING:
        raise PermissionError("Harness selected an unexpected brand asset executor")

    capability_authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{PRODUCTION_BRAND_ASSET_CAPABILITY_ID}",
        harness_decision_id=parent_authorization.harness_decision_id,
        execution_id=parent_authorization.execution_id,
        lineage={
            "parent_authorization_id": parent_authorization.authorization_id,
            "routing_id": routing.routing_id,
            "capability_id": PRODUCTION_BRAND_ASSET_CAPABILITY_ID,
            "selected_executor_binding": PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING,
            "content_item_id": content_item_id,
        },
    )
    return bind_active_brand_assets(
        content_item_id=content_item_id,
        authorization=capability_authorization,
        routing_decision=routing,
        execution_id=parent_authorization.execution_id,
    )


def _resolve_execution_goal(*, authorization, requested_goal_id: str | None) -> dict[str, Any] | None:
    """Resolve the exact Harness-targeted Goal, falling back only for legacy untargeted calls."""
    lineage_goal_id = authorization.lineage.get("goal_id")
    if requested_goal_id is not None:
        if not isinstance(requested_goal_id, str) or not requested_goal_id.strip():
            raise PermissionError("Harness goal_id must be a non-empty string")
        requested_goal_id = requested_goal_id.strip()
        if lineage_goal_id != requested_goal_id:
            raise PermissionError("Harness authorization goal_id lineage mismatch")
        goal = get_gta6_goal(requested_goal_id)
        if goal is None:
            raise RuntimeError(f"Harness-targeted Goal not found: {requested_goal_id}")
        return goal

    if lineage_goal_id is not None:
        raise PermissionError("Harness authorization contains goal_id but execution did not target it")
    return get_active_gta6_goal()


def process_next_production_execution(
    execution_context: dict[str, Any] | None = None,
    *,
    goal_id: str | None = None,
) -> dict[str, Any] | None:
    """Advance one Harness-authorized production execution step for an exact Goal when targeted."""
    context = execution_context or {}
    execution_id = context.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise PermissionError("Harness execution_id is required for EXECUTION")

    authorization = validate_harness_authorization(
        context,
        expected_action="EXECUTION",
        expected_subject="action:EXECUTION",
        expected_execution_id=execution_id,
    )
    execution_context = authorization_to_context(authorization)
    goal = _resolve_execution_goal(
        authorization=authorization,
        requested_goal_id=goal_id,
    )
    if goal is None:
        return None

    resolved_goal_id = goal["goal_id"]
    resolution = resolve_next_stage(goal_id=resolved_goal_id)
    next_stage = resolution.get("next_stage")

    if next_stage == "VIDEO":
        artifacts = get_artifacts(goal_id=resolved_goal_id)
        content_item_id = artifacts.get("content_item_id")
        if not isinstance(content_item_id, int) or content_item_id <= 0:
            raise RuntimeError("Goal em VIDEO não possui content_item_id válido.")

        stored_plan = get_production_plan_by_content_item_id(content_item_id)
        if stored_plan is None:
            raise RuntimeError("Content Item não possui Production Plan persistido.")
        production_plan = stored_plan.get("production_plan")
        if not isinstance(production_plan, dict):
            raise RuntimeError("Production Plan persistido é inválido.")

        media_result = _govern_production_media_binding(
            parent_authorization=authorization,
            production_plan=production_plan,
        )
        production_plan = media_result["production_plan"]
        brand_result = _govern_brand_asset_binding(
            parent_authorization=authorization,
            content_item_id=content_item_id,
        )

        video_spec = create_video_spec(production_plan, brain_decision=execution_context)
        # Snapshot only into this newly created execution contract. Existing
        # RenderJobs are never retroactively mutated by a Telegram asset change.
        video_spec["brand_assets"] = list(brand_result["brand_assets"])
        composed = create_video_and_enqueue_render(video_spec)
        video = composed["video"]
        render_job = composed["render_job"]
        video_id = video.get("id")
        render_job_id = render_job.get("id")
        if not isinstance(video_id, int) or video_id <= 0:
            raise RuntimeError("Video criado não possui id válido.")
        if not isinstance(render_job_id, int) or render_job_id <= 0:
            raise RuntimeError("Render Job criado não possui id válido.")
        update_artifacts(goal_id=resolved_goal_id, video_id=video_id, render_job_id=render_job_id)
        return {
            "goal_id": resolved_goal_id,
            "stage": "VIDEO",
            "video": video,
            "render_job": render_job,
            "media_execution": media_result["canonical_execution_result"],
            "brand_asset_execution": brand_result["canonical_execution_result"],
            "brand_asset_count": brand_result["asset_count"],
        }

    if next_stage == "RENDER":
        if goal_id is None:
            result = process_next_render_job(execution_context=execution_context)
        else:
            artifacts = get_artifacts(goal_id=resolved_goal_id)
            render_job_id = artifacts.get("render_job_id")
            if not isinstance(render_job_id, int) or render_job_id <= 0:
                raise RuntimeError("Targeted Goal em RENDER não possui render_job_id válido.")
            result = process_render_job(
                render_job_id,
                execution_context=execution_context,
            )
        return {"goal_id": resolved_goal_id, "stage": "RENDER", "result": result}

    return {"goal_id": resolved_goal_id, "stage": next_stage, "status": "nothing_to_execute"}
