from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.database.production_plan_repository import (
    get_production_plan_by_content_item_id,
    insert_production_plan,
)
from app.services.production_plan_service import create_production_plan
from app.services.gta6_media_discovery_service import discover_gta6_media_candidates
from app.services.render_artifact_validator import RenderArtifactValidator
from app.services.script_generator_service import generate_and_save_script
from app.services.vedit_service import create_edit_plan


BINDINGS = {
    "media.discovery": "app.services.native_capability_adapters.execute_media_discovery_capability",
    "production.plan": "app.services.native_capability_adapters.execute_production_plan_capability",
    "qa.preflight": "app.services.native_capability_adapters.execute_qa_preflight_capability",
    "script.generate": "app.services.native_capability_adapters.execute_script_generate_capability",
    "video.edit.vedit": "app.services.native_capability_adapters.execute_vedit_plan_capability",
}


def _validate(capability: Any, capability_id: str) -> None:
    if getattr(capability, "capability_id", None) != capability_id:
        raise PermissionError(f"{capability_id} adapter received a different capability")
    expected = BINDINGS[capability_id]
    if getattr(capability, "executor_binding", None) != expected:
        raise PermissionError(f"{capability_id} executor binding mismatch")


def execute_media_discovery_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _validate(capability, "media.discovery")
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("media.discovery requires results list")
    topic = payload.get("topic")
    if topic is not None and not isinstance(topic, str):
        raise ValueError("media.discovery topic must be a string or null")
    candidates = discover_gta6_media_candidates(results, topic=topic)
    return {
        "status": "EXECUTED",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def execute_production_plan_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _validate(capability, "production.plan")
    context = payload.get("context")
    if not isinstance(context, dict):
        raise ValueError("production.plan requires dependency artifact context")
    parents = [
        dict(item)
        for item in (context.get("parent_handoffs") or ())
        if isinstance(item, dict) and item.get("direct_dependency") is True
    ]
    if not parents:
        raise ValueError("production.plan requires direct dependency artifact")
    input_refs: list[str] = []
    parent_content_item = None
    for parent in parents:
        ref = str(parent.get("task_result_ref") or "").strip()
        digest = str(parent.get("content_sha256") or "").strip()
        if not ref.startswith("artifact:") or len(digest) != 64:
            raise ValueError("production.plan dependency artifact lineage is invalid")
        if ref not in input_refs:
            input_refs.append(ref)
        result = parent.get("result")
        if isinstance(result, dict):
            candidate = result.get("content_item")
            if isinstance(candidate, dict):
                parent_content_item = dict(candidate)
    content_item = payload.get("content_item")
    if content_item is None:
        content_item = parent_content_item
    if not isinstance(content_item, dict):
        raise ValueError("production.plan requires content_item from dependency artifact")
    if (
        parent_content_item is not None
        and content_item.get("id") != parent_content_item.get("id")
    ):
        raise PermissionError("production.plan content_item drifted from dependency artifact")
    content_item_id = content_item.get("id")
    if (
        isinstance(content_item_id, bool)
        or not isinstance(content_item_id, int)
        or content_item_id <= 0
    ):
        raise ValueError("production.plan requires persisted positive content_item id")

    stored = get_production_plan_by_content_item_id(content_item_id)
    if stored is None:
        plan = create_production_plan(content_item)
        production_plan_id = insert_production_plan(
            content_item_id=content_item_id,
            production_plan=plan,
        )
        reused = False
    else:
        plan = stored["production_plan"]
        production_plan_id = int(stored["id"])
        reused = True
    return {
        "status": "EXECUTED",
        "production_plan": plan,
        "production_plan_id": production_plan_id,
        "artifact_ref": f"production-plan:{production_plan_id}",
        "input_refs": input_refs,
        "direct_lineage_preserved": True,
        "idempotent": reused,
    }


def execute_qa_preflight_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _validate(capability, "qa.preflight")
    output_path = payload.get("output_path")
    if not isinstance(output_path, str) or not output_path.strip():
        raise ValueError("qa.preflight requires output_path")
    result = RenderArtifactValidator().validate(output_path.strip())
    return {
        "status": "PASS" if result.valid else "FAIL",
        "validation": asdict(result),
    }


def execute_script_generate_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _validate(capability, "script.generate")
    idea_id = payload.get("idea_id")
    if isinstance(idea_id, bool) or not isinstance(idea_id, int) or idea_id <= 0:
        raise ValueError("script.generate requires positive idea_id")
    target = payload.get("target_duration_seconds")
    if target is not None:
        if isinstance(target, bool) or not isinstance(target, (int, float)) or target <= 0:
            raise ValueError("target_duration_seconds must be positive")
        target = float(target)
    # This legacy capability intentionally uses the deterministic generator only.
    # AI-backed editorial generation remains on the dedicated Harness provider path.
    script_id = generate_and_save_script(
        idea_id,
        ai_provider=None,
        target_duration_seconds=target,
    )
    return {
        "status": "EXECUTED",
        "script_id": script_id,
        "generation_mode": "DETERMINISTIC_LEGACY",
    }


def execute_vedit_plan_capability(
    capability: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _validate(capability, "video.edit.vedit")
    production_plan = payload.get("production_plan")
    if not isinstance(production_plan, dict):
        raise ValueError("video.edit.vedit requires production_plan object")
    brain_decision = payload.get("brain_decision")
    if brain_decision is not None and not isinstance(brain_decision, dict):
        raise ValueError("brain_decision must be an object or null")
    plan = create_edit_plan(
        production_plan=production_plan,
        brain_decision=brain_decision,
    )
    to_dict = getattr(plan, "to_dict", None)
    serialized = to_dict() if callable(to_dict) else asdict(plan)
    return {
        "status": "EXECUTED",
        "edit_plan": serialized,
    }
