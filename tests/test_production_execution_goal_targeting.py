import pytest

import app.services.production_execution_service as execution_service
from app.database.gta6_goal_repository import get_gta6_goal
from app.services.gta6_goal_service import create_goal, set_goal_status
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.production_execution_service import process_next_production_execution


def _active_goal(topic: str):
    goal = create_goal(
        goal_type="EVERGREEN",
        topic=topic,
        priority="HIGH",
        opportunity_score=9.0,
        target_duration="45s",
    )
    return set_goal_status(goal_id=goal["goal_id"], status="ACTIVE")


def _execution_context(goal_id: str):
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        lineage={
            "goal_id": goal_id,
            "zero_cost_operation": True,
            "purpose": "run-001-canary",
        },
    )
    return authorization, authorization_to_context(authorization)


def test_targeted_execution_ignores_other_active_goal_and_preserves_it():
    frozen = _active_goal("frozen-job18-goal")
    canary = _active_goal("independent-run001-canary")
    frozen_before = get_gta6_goal(frozen["goal_id"])

    authorization, context = _execution_context(canary["goal_id"])
    result = process_next_production_execution(
        context,
        goal_id=canary["goal_id"],
    )

    assert result["goal_id"] == canary["goal_id"]
    assert result["stage"] == "RESEARCH"
    assert result["status"] == "nothing_to_execute"
    assert authorization.execution_id == context["execution_id"]
    assert get_gta6_goal(frozen["goal_id"]) == frozen_before


def test_targeted_execution_fails_closed_on_goal_lineage_mismatch():
    first = _active_goal("first-goal")
    second = _active_goal("second-goal")
    _, context = _execution_context(first["goal_id"])

    with pytest.raises(PermissionError, match="goal_id lineage mismatch"):
        process_next_production_execution(
            context,
            goal_id=second["goal_id"],
        )


def test_untargeted_execution_rejects_goal_scoped_authorization():
    goal = _active_goal("scoped-goal")
    _, context = _execution_context(goal["goal_id"])

    with pytest.raises(PermissionError, match="did not target"):
        process_next_production_execution(context)


def test_targeted_render_executes_only_render_job_attached_to_goal(monkeypatch):
    frozen = _active_goal("frozen-job18-goal-render-boundary")
    target = _active_goal("independent-run001-target-render")
    frozen_before = get_gta6_goal(frozen["goal_id"])
    _, context = _execution_context(target["goal_id"])
    calls = []

    monkeypatch.setattr(
        execution_service,
        "resolve_next_stage",
        lambda **_: {"next_stage": "RENDER"},
    )
    monkeypatch.setattr(
        execution_service,
        "get_artifacts",
        lambda **_: {"render_job_id": 222},
    )

    def exact_render(job_id, *, execution_context=None):
        calls.append((job_id, execution_context))
        return {"success": True, "job_id": job_id}

    monkeypatch.setattr(execution_service, "process_render_job", exact_render)
    monkeypatch.setattr(
        execution_service,
        "process_next_render_job",
        lambda **_: pytest.fail("targeted execution must not claim the global next RenderJob"),
    )

    result = process_next_production_execution(
        context,
        goal_id=target["goal_id"],
    )

    assert result["goal_id"] == target["goal_id"]
    assert result["stage"] == "RENDER"
    assert result["result"]["job_id"] == 222
    assert calls == [(222, context)]
    assert get_gta6_goal(frozen["goal_id"]) == frozen_before


def test_video_stage_selects_missing_segments_from_explicit_knowledge_before_binding(monkeypatch):
    target = _active_goal("run001-explicit-media-selection")
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        lineage={"goal_id": target["goal_id"], "knowledge_id": 7},
    )
    context = authorization_to_context(authorization)
    plan = {
        "content_item_id": 4,
        "script_id": 8,
        "idea_id": 2,
        "scenes": [{"order": 1}, {"order": 2}],
    }
    calls = []
    monkeypatch.setattr(execution_service, "resolve_next_stage", lambda **_: {"next_stage": "VIDEO"})
    monkeypatch.setattr(execution_service, "get_artifacts", lambda **_: {"content_item_id": 4})
    monkeypatch.setattr(
        execution_service,
        "get_production_plan_by_content_item_id",
        lambda _id: {"production_plan": plan},
    )
    monkeypatch.setattr(
        execution_service,
        "_govern_production_media_selection",
        lambda **kwargs: calls.append(("select", kwargs)) or {
            "segment_ids": [101, 102],
            "canonical_execution_result": {"success": True},
        },
    )
    monkeypatch.setattr(
        execution_service,
        "_govern_production_media_binding",
        lambda **kwargs: calls.append(("bind", kwargs)) or {
            "production_plan": {
                **plan,
                "scenes": [{"order": 1, "segment_id": 101}, {"order": 2, "segment_id": 102}],
            },
            "canonical_execution_result": {"success": True},
        },
    )
    monkeypatch.setattr(
        execution_service,
        "_govern_brand_asset_binding",
        lambda **_: {
            "brand_assets": [],
            "asset_count": 0,
            "canonical_execution_result": {"success": True},
        },
    )
    monkeypatch.setattr(execution_service, "create_video_spec", lambda *_a, **_k: {})
    monkeypatch.setattr(
        execution_service,
        "create_video_and_enqueue_render",
        lambda _spec: {"video": {"id": 31}, "render_job": {"id": 41}},
    )
    monkeypatch.setattr(execution_service, "update_artifacts", lambda **_: None)

    result = process_next_production_execution(
        context,
        goal_id=target["goal_id"],
        knowledge_id=7,
    )

    assert [name for name, _ in calls] == ["select", "bind"]
    assert calls[0][1]["knowledge_id"] == 7
    assert calls[1][1]["production_plan"]["scenes"][0]["segment_id"] == 101
    assert result["media_selection_execution"]["success"] is True


def test_video_stage_without_selected_segments_requires_explicit_knowledge(monkeypatch):
    target = _active_goal("run001-missing-explicit-media-selection")
    _, context = _execution_context(target["goal_id"])
    monkeypatch.setattr(execution_service, "resolve_next_stage", lambda **_: {"next_stage": "VIDEO"})
    monkeypatch.setattr(execution_service, "get_artifacts", lambda **_: {"content_item_id": 4})
    monkeypatch.setattr(
        execution_service,
        "get_production_plan_by_content_item_id",
        lambda _id: {
            "production_plan": {
                "content_item_id": 4,
                "script_id": 8,
                "idea_id": 2,
                "scenes": [{"order": 1}],
            }
        },
    )

    with pytest.raises(RuntimeError, match="knowledge_id explícito"):
        process_next_production_execution(context, goal_id=target["goal_id"])
