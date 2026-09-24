from typing import Any
import math

from app.database.production_plan_repository import (
    get_production_plan_by_content_item_id,
    insert_production_plan,
)
from app.database.gta6_goal_repository import (
    get_gta6_goal_artifacts,
    get_gta6_goal_artifacts_by_idea_id,
)
from app.database.queue_repository import (
    claim_next_queue_item,
    claim_queue_item_by_id,
    get_active_queue_item_by_idea,
    mark_queue_item_completed,
    requeue_processing_queue_item_by_id,
)
from app.database.scripts_repository import get_script
from app.services.ai_provider import AIProvider
from app.services.content_item_service import create_content_item
from app.services.production_plan_service import create_production_plan
from app.services.gta6_goal_service import update_artifacts
from app.services.script_generator_service import generate_and_save_script
from app.services.script_spec_service import generate_script_spec
from app.services.harness_authorization_service import (
    authorization_to_context,
    validate_harness_authorization,
)


def _positive_int(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
    )


def _resolve_targeted_editorial_state(
    *,
    goal_id: str,
    authorization,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not isinstance(goal_id, str) or not goal_id.strip():
        raise PermissionError("Harness goal_id must be a non-empty string")
    goal_id = goal_id.strip()

    lineage_goal_id = authorization.lineage.get("goal_id")
    if lineage_goal_id != goal_id:
        raise PermissionError("Harness authorization goal_id lineage mismatch")

    artifacts = get_gta6_goal_artifacts(goal_id)
    if artifacts is None:
        raise RuntimeError(f"Harness-targeted Goal artifacts not found: {goal_id}")

    idea_id = artifacts.get("idea_id")
    if not _positive_int(idea_id):
        raise RuntimeError("Harness-targeted Goal does not have a valid idea_id")

    script_id = artifacts.get("script_id")
    content_item_id = artifacts.get("content_item_id")
    if _positive_int(script_id) and _positive_int(content_item_id):
        stored_plan = get_production_plan_by_content_item_id(content_item_id)
        if stored_plan is not None:
            script = get_script(script_id)
            if script is None:
                raise RuntimeError(
                    f"Persisted targeted Script could not be recovered: {script_id}"
                )
            return artifacts, {
                "queue_item": None,
                "script": script,
                "script_spec": None,
                "content_item": {"id": content_item_id},
                "production_plan_id": stored_plan["id"],
                "production_plan": stored_plan["production_plan"],
                "status": "completed",
                "goal_id": goal_id,
                "idempotent": True,
            }

    if _positive_int(artifacts.get("render_job_id")):
        raise RuntimeError(
            "Targeted Goal has a RenderJob before editorial lineage is complete"
        )

    return artifacts, None


def process_next_editorial_queue_item(
    *,
    ai_provider: AIProvider | None = None,
    brain_decision: dict[str, Any] | None = None,
    execution_context: dict[str, Any] | None = None,
    goal_id: str | None = None,
    editorial_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Consome uma única entrada da fila editorial.

    Chamadas targeted vinculam autorização, Goal, Idea e queue_id de forma
    determinística. Chamadas legacy sem goal_id preservam o claim global.

    A etapa editorial não cria Video Spec, Render Job ou executa render.
    """

    context = execution_context or {}
    execution_id = context.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise PermissionError("Harness execution_id is required for EDITORIAL")
    authorization = validate_harness_authorization(
        context,
        expected_action="EDITORIAL",
        expected_subject="action:EDITORIAL",
        expected_execution_id=execution_id,
    )
    execution_context = authorization_to_context(authorization)

    target_duration_seconds = authorization.lineage.get("target_duration_seconds")
    if target_duration_seconds is not None:
        if (
            isinstance(target_duration_seconds, bool)
            or not isinstance(target_duration_seconds, (int, float))
            or not math.isfinite(float(target_duration_seconds))
            or float(target_duration_seconds) <= 0
        ):
            raise PermissionError("Harness target_duration_seconds must be finite and positive")
        target_duration_seconds = float(target_duration_seconds)

    lineage_goal_id = authorization.lineage.get("goal_id")
    targeted_artifacts: dict[str, Any] | None = None
    if goal_id is None:
        if lineage_goal_id is not None:
            raise PermissionError(
                "Harness authorization contains goal_id but editorial did not target it"
            )
        queue_item = claim_next_queue_item()
    else:
        targeted_artifacts, existing = _resolve_targeted_editorial_state(
            goal_id=goal_id,
            authorization=authorization,
        )
        if existing is not None:
            existing["harness_context"] = execution_context
            return existing

        idea_id = targeted_artifacts["idea_id"]
        queue_candidate = get_active_queue_item_by_idea(idea_id)
        if queue_candidate is None:
            return None

        queue_id = queue_candidate.get("id")
        if not _positive_int(queue_id):
            raise RuntimeError("Targeted editorial queue item has an invalid id")

        queue_item = claim_queue_item_by_id(queue_id)
        if queue_item is None:
            raise RuntimeError(
                "Targeted editorial queue item could not be atomically claimed"
            )

    if queue_item is None:
        return None

    queue_id = queue_item.get("id")
    idea_id = queue_item.get("idea_id")

    if not _positive_int(queue_id):
        raise RuntimeError(
            "Item da fila não possui um id persistido válido."
        )

    if not _positive_int(idea_id):
        raise RuntimeError(
            "Item da fila não possui um idea_id persistido válido."
        )

    if targeted_artifacts is not None and idea_id != targeted_artifacts.get("idea_id"):
        raise PermissionError("Targeted editorial claim resolved a different Idea")

    try:
        if ai_provider is None:
            if target_duration_seconds is None:
                script_id = generate_and_save_script(idea_id)
            else:
                script_id = generate_and_save_script(
                    idea_id,
                    editorial_context=editorial_context,
                    target_duration_seconds=target_duration_seconds,
                )
        else:
            if target_duration_seconds is None:
                script_id = generate_and_save_script(
                    idea_id,
                    ai_provider=ai_provider,
                    editorial_context=editorial_context,
                )
            else:
                script_id = generate_and_save_script(
                    idea_id,
                    ai_provider=ai_provider,
                    editorial_context=editorial_context,
                    target_duration_seconds=target_duration_seconds,
                )
    except Exception:
        # A targeted longform generation may fail before any Script/ContentItem
        # is persisted (for example, insufficient factual evidence). Release
        # only this known processing claim so the same Harness-authorized Goal
        # can be retried after bounded evidence recovery. Never requeue after
        # downstream editorial persistence has started.
        if targeted_artifacts is not None:
            if not requeue_processing_queue_item_by_id(
                queue_id,
                expected_idea_id=idea_id,
            ):
                raise RuntimeError(
                    "Targeted editorial queue claim could not be safely "
                    "requeued after script generation failure"
                )
        raise

    if not _positive_int(script_id):
        raise RuntimeError(
            "Script criado não possui um script_id persistido válido."
        )

    script = get_script(script_id)

    if script is None:
        raise RuntimeError(
            f"Script criado não pôde ser recuperado: {script_id}."
        )

    script_spec = generate_script_spec(script_id)
    script_spec = dict(script_spec)
    if target_duration_seconds is not None:
        script_spec["estimated_duration_seconds"] = target_duration_seconds
    if editorial_context:
        verified_claims = editorial_context.get("verified_claims")
        if isinstance(verified_claims, list):
            script_spec["verified_claims"] = [dict(item) for item in verified_claims if isinstance(item, dict)]
        strategy = editorial_context.get("youtube_strategy")
        if strategy is None:
            strategy = editorial_context.get("content_strategy_analysis")
        if strategy is not None:
            script_spec["youtube_strategy"] = strategy
        refs = editorial_context.get("content_strategy_evidence_refs")
        if isinstance(refs, (list, tuple)):
            script_spec["editorial_evidence_refs"] = [
                str(item) for item in refs if str(item).strip()
            ]
    content_item = create_content_item(script_spec)

    production_plan = create_production_plan(content_item)
    production_plan_id = insert_production_plan(
        content_item_id=content_item["id"],
        production_plan=production_plan,
    )

    if targeted_artifacts is not None:
        resolved_goal_id = goal_id.strip()
    else:
        goal_artifacts = get_gta6_goal_artifacts_by_idea_id(idea_id)
        resolved_goal_id = (
            goal_artifacts.get("goal_id")
            if goal_artifacts is not None
            else None
        )

    if resolved_goal_id is not None:
        if not isinstance(resolved_goal_id, str) or not resolved_goal_id.strip():
            raise RuntimeError(
                "Goal associado à Idea possui goal_id inválido."
            )

        update_artifacts(
            goal_id=resolved_goal_id,
            script_id=script_id,
            content_item_id=content_item["id"],
        )

    completed = mark_queue_item_completed(queue_id)

    if not completed:
        raise RuntimeError(
            "Não foi possível marcar o item da fila como completed."
        )

    result = {
        "queue_item": queue_item,
        "script": script,
        "script_spec": script_spec,
        "content_item": content_item,
        "production_plan_id": production_plan_id,
        "production_plan": production_plan,
        "status": "completed",
        "harness_context": execution_context,
    }
    if targeted_artifacts is not None:
        result["goal_id"] = resolved_goal_id
        result["idempotent"] = False
    return result
