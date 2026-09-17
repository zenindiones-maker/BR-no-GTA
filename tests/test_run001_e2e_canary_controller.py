from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.run001_e2e_canary_controller import (
    E2ECanaryControllerError,
    RENDER_WORKFLOW,
    SCHEMA,
    build_canary_bundle,
    validate_request,
)


def _request(**overrides):
    value = {
        "schema": SCHEMA,
        "render_job_id": 910001,
        "video_id": 910001,
        "content_item_id": 910001,
        "script_id": 910001,
        "idea_id": 910001,
        "goal_id": "run001-e2e-canary-v1",
        "execution_id": "run001-e2e-canary-v1",
        "estimated_duration_seconds": 45.0,
        "source_url": "https://www.youtube.com/watch?v=QdBZY2fkU-0",
        "source_start_seconds": 5.0,
        "review_only": True,
        "youtube_publication": False,
    }
    value.update(overrides)
    return value


def _bundle(request=None):
    routing = SimpleNamespace(
        routing_id="routing-canary",
        selected_capability_id="media.ffmpeg",
        selected_executor_binding="app.workers.audiovisual_worker.execute_cloud",
    )
    authorization = SimpleNamespace(
        authorization_id="authorization-canary",
        harness_decision_id="decision-canary",
        authorized_action="EXECUTION",
        execution_id="run001-e2e-canary-v1",
    )
    context = {
        "harness_decision_id": "decision-canary",
        "brain_decision_id": "decision-canary",
        "execution_id": "run001-e2e-canary-v1",
        "authorized_action": "EXECUTION",
        "issued_by": "deepseek_harness",
        "lineage": {},
    }
    with patch("scripts.run001_e2e_canary_controller.initialize_application"), patch(
        "scripts.run001_e2e_canary_controller.route_harness_request",
        return_value=routing,
    ) as route, patch(
        "scripts.run001_e2e_canary_controller.issue_harness_authorization",
        return_value=authorization,
    ) as issue, patch(
        "scripts.run001_e2e_canary_controller.validate_harness_authorization",
        return_value=authorization,
    ) as validate, patch(
        "scripts.run001_e2e_canary_controller.authorization_to_context",
        return_value=context,
    ):
        bundle = build_canary_bundle(request or _request())
    return bundle, route, issue, validate


def test_short_canary_is_canonical_and_routes_through_official_worker() -> None:
    bundle, route, issue, validate = _bundle()
    job = bundle["render-job"]
    evidence = bundle["controller-evidence"]

    assert RENDER_WORKFLOW == ".github/workflows/render-worker.yml"
    assert evidence["render_workflow"] == RENDER_WORKFLOW
    assert evidence["status"] == "AUTHORIZED_FOR_RENDER_DISPATCH"
    assert evidence["authorization_id"] == "authorization-canary"
    assert evidence["selected_capability_id"] == "media.ffmpeg"
    assert evidence["authorized_action"] == "EXECUTION"
    assert evidence["target_human_review_state"] == "READY_FOR_HUMAN_REVIEW"
    assert evidence["job18_unchanged"] is True
    assert evidence["job20_reused_as_final"] is False
    assert evidence["youtube_publication"] is False

    assert job["render_job_id"] == 910001
    assert job["video_id"] == 910001
    assert job["content_item_id"] == 910001
    assert job["script_id"] == 910001
    assert job["goal_id"] == "run001-e2e-canary-v1"
    assert job["execution_id"] == "run001-e2e-canary-v1"
    assert job["brain_decision_id"] == "decision-canary"
    assert job["authorized_action"] == "EXECUTION"
    assert job["issued_by"] == "deepseek_harness"
    assert job["estimated_duration_seconds"] == 45.0
    assert job["review_only"] is True
    assert job["youtube_publication"] is False
    assert job["youtube_publication_authority"] == "NONE"
    assert job["human_review_state"] == "NOT_DELIVERED"
    assert job["edit_plan"]["duration_seconds"] == 45.0
    assert job["edit_plan"]["metadata"]["render_worker"] == RENDER_WORKFLOW
    assert job["scenes"][0]["asset_ref"].startswith("remote://media-worker/")
    assert job["audio_requirements"][0]["asset_ref"] == job["scenes"][0]["asset_ref"]
    assert job["scenes"][0]["source_url"] == "https://www.youtube.com/watch?v=QdBZY2fkU-0"
    assert sorted((item["asset_id"], item["asset_type"]) for item in job["brand_assets"]) == [
        (1, "intro"),
        (2, "watermark"),
    ]

    route_request = route.call_args.args[0]
    assert route_request.authorized_action == "EXECUTION"
    assert route_request.required_capability_id == "media.ffmpeg"
    assert route_request.fallback_allowed is False
    assert issue.call_args.kwargs["authorized_action"] == "EXECUTION"
    assert issue.call_args.kwargs["subject"] == "action:EXECUTION"
    assert issue.call_args.kwargs["execution_id"] == "run001-e2e-canary-v1"
    assert validate.call_args.kwargs["expected_action"] == "EXECUTION"
    assert validate.call_args.kwargs["expected_subject"] == "action:EXECUTION"


def test_duration_must_stay_inside_30_to_60_seconds() -> None:
    assert validate_request(_request(estimated_duration_seconds=30))["estimated_duration_seconds"] == 30.0
    assert validate_request(_request(estimated_duration_seconds=60))["estimated_duration_seconds"] == 60.0
    for duration in (0, 29.999, 60.001, 1500):
        with pytest.raises(E2ECanaryControllerError):
            validate_request(_request(estimated_duration_seconds=duration))


@pytest.mark.parametrize("render_job_id", [18, 20])
def test_job18_and_job20_are_forbidden(render_job_id: int) -> None:
    with pytest.raises(E2ECanaryControllerError):
        validate_request(_request(render_job_id=render_job_id))


def test_publication_and_review_guards_fail_closed() -> None:
    with pytest.raises(E2ECanaryControllerError):
        validate_request(_request(review_only=False))
    with pytest.raises(E2ECanaryControllerError):
        validate_request(_request(youtube_publication=True))


def test_correlation_ids_are_preserved_across_canonical_objects() -> None:
    bundle, _, _, _ = _bundle()
    goal = bundle["goal"]
    video = bundle["video"]
    content = bundle["content-item"]
    script = bundle["script"]
    job = bundle["render-job"]
    evidence = bundle["controller-evidence"]

    assert goal["goal_id"] == video["goal_id"] == content["goal_id"] == job["goal_id"] == evidence["goal_id"]
    assert goal["render_job_id"] == video["render_job_id"] == job["render_job_id"] == evidence["render_job_id"]
    assert goal["video_id"] == video["video_id"] == job["video_id"] == evidence["video_id"]
    assert video["content_item_id"] == content["content_item_id"] == job["content_item_id"] == evidence["content_item_id"]
    assert video["script_id"] == script["script_id"] == job["script_id"] == evidence["script_id"]
    assert video["execution_id"] == job["execution_id"] == evidence["execution_id"]
