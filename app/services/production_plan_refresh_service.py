from __future__ import annotations

from typing import Any

from app.database.production_plan_repository import update_production_plan
from app.services.production_plan_service import create_production_plan
from app.services.script_spec_service import generate_script_spec


def refresh_production_plan_from_persisted_script(
    *,
    content_item_id: int,
    script_id: int,
    existing_plan: dict[str, Any],
    target_duration_seconds: float,
) -> dict[str, Any]:
    """Rebuild deterministic production structure without creating a new ContentItem."""
    if content_item_id <= 0 or script_id <= 0:
        raise ValueError("content_item_id and script_id must be positive")
    if not isinstance(existing_plan, dict) or not existing_plan:
        raise ValueError("existing_plan is required")

    script_spec = dict(generate_script_spec(script_id))
    script_spec["estimated_duration_seconds"] = float(target_duration_seconds)
    script_spec["verified_claims"] = [
        dict(item) for item in (existing_plan.get("verified_claims") or [])
        if isinstance(item, dict)
    ]
    script_spec["youtube_strategy"] = existing_plan.get("youtube_strategy")
    script_spec["editorial_evidence_refs"] = list(
        existing_plan.get("editorial_evidence_refs") or []
    )
    content_item = {
        "id": content_item_id,
        "script_id": script_spec["script_id"],
        "idea_id": script_spec["idea_id"],
        "title": str(existing_plan.get("title") or script_spec.get("title") or "").strip(),
        "description": str(existing_plan.get("description") or "").strip(),
        "format": script_spec["format"],
        "objective": script_spec["objective"],
        "audience": script_spec["audience"],
        "estimated_duration_seconds": script_spec["estimated_duration_seconds"],
        "tone": script_spec["tone"],
        "hook": script_spec["hook"],
        "narrative_blocks": script_spec["narrative_blocks"],
        "facts_sources": script_spec["facts_sources"],
        "verified_claims": script_spec["verified_claims"],
        "youtube_strategy": script_spec["youtube_strategy"],
        "editorial_evidence_refs": script_spec["editorial_evidence_refs"],
        "cta": script_spec["cta"],
        "visual_requirements": script_spec["visual_requirements"],
        "status": "ready",
    }
    production_plan = create_production_plan(content_item)
    if not update_production_plan(
        content_item_id=content_item_id,
        production_plan=production_plan,
    ):
        raise RuntimeError("failed to persist refreshed ProductionPlan")
    return {
        "script_spec": script_spec,
        "content_item": content_item,
        "production_plan": production_plan,
    }
