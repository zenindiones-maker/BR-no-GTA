from types import SimpleNamespace

import pytest

from app.services.capability_execution_contract_service import (
    CAN_MUTATE_CANDIDATE,
    CAN_READ_REPOSITORY,
    CAN_REVIEW,
    CAN_RUN_BENCHMARK,
)
from app.services.task_dependency_precondition_service import (
    TaskDependencyPreconditionFailure,
    validate_task_dependency_preconditions,
)


def _task(task_id, ops, *, deps=(), agent="agent", skill=None, capability="cap"):
    return SimpleNamespace(
        task_id=task_id,
        required_operations=tuple(ops),
        dependencies=tuple(deps),
        selected_agent_id=agent,
        selected_skill_id=skill,
        capability_id=capability,
    )


def test_review_fails_closed_before_provider_when_candidate_artifact_missing():
    candidate = _task(
        "candidate",
        (CAN_MUTATE_CANDIDATE,),
        agent="builder",
        capability="builder-cap",
    )
    review = _task(
        "review",
        (CAN_REVIEW,),
        deps=("candidate",),
        agent="reviewer",
        capability="review-cap",
    )
    tasks = {"candidate": candidate, "review": review}
    context = {
        "dependency_results": [{
            "task_id": "candidate",
            "direct_dependency": True,
            "task_result_ref": "artifact:task-results/candidate-1.json",
            "content_sha256": "abc",
            "result": {"summary": "text recommendations only"},
            "output_artifact_refs": [],
        }]
    }
    with pytest.raises(
        TaskDependencyPreconditionFailure,
        match="REVIEW_BLOCKED_BY_MISSING_CANDIDATE",
    ) as caught:
        validate_task_dependency_preconditions(
            task=review,
            dependency_context=context,
            task_lookup=tasks.__getitem__,
        )
    assert caught.value.details["provider_call_executed"] is False


def test_review_requires_independent_owner_when_candidate_exists():
    candidate = _task(
        "candidate",
        (CAN_MUTATE_CANDIDATE,),
        agent="same",
        capability="same-cap",
    )
    review = _task(
        "review",
        (CAN_REVIEW,),
        deps=("candidate",),
        agent="same",
        capability="same-cap",
    )
    tasks = {"candidate": candidate, "review": review}
    context = {
        "dependency_results": [{
            "task_id": "candidate",
            "direct_dependency": True,
            "task_result_ref": "artifact:task-results/candidate-1.json",
            "content_sha256": "abc",
            "result": {"candidate_sha": "a" * 40},
            "output_artifact_refs": ["git-commit:" + "a" * 40],
        }]
    }
    with pytest.raises(
        TaskDependencyPreconditionFailure,
        match="REVIEWER_NOT_INDEPENDENT",
    ):
        validate_task_dependency_preconditions(
            task=review,
            dependency_context=context,
            task_lookup=tasks.__getitem__,
        )


def test_benchmark_requires_real_candidate_and_baseline_artifacts():
    profile = _task(
        "profile",
        (CAN_READ_REPOSITORY,),
        agent="profiler",
        capability="profile-cap",
    )
    candidate = _task(
        "candidate",
        (CAN_MUTATE_CANDIDATE,),
        deps=("profile",),
        agent="builder",
        capability="builder-cap",
    )
    benchmark = _task(
        "benchmark",
        (CAN_RUN_BENCHMARK,),
        deps=("candidate",),
        agent="bench",
        capability="bench-cap",
    )
    tasks = {
        "profile": profile,
        "candidate": candidate,
        "benchmark": benchmark,
    }
    context = {
        "dependency_results": [
            {
                "task_id": "candidate",
                "direct_dependency": True,
                "task_result_ref": "artifact:task-results/candidate-1.json",
                "content_sha256": "candidate",
                "result": {"candidate_sha": "a" * 40},
                "output_artifact_refs": ["git-commit:" + "a" * 40],
            },
            {
                "task_id": "profile",
                "direct_dependency": False,
                "task_result_ref": "artifact:task-results/profile-1.json",
                "content_sha256": "profile",
                "result": {"BASELINE_MS": 14105.371},
                "output_artifact_refs": [],
            },
        ]
    }
    result = validate_task_dependency_preconditions(
        task=benchmark,
        dependency_context=context,
        task_lookup=tasks.__getitem__,
    )
    assert result["status"] == "PASS"
    assert result["baseline_task_ids"] == ["profile"]
    assert result["candidate_artifact_refs"] == ["git-commit:" + "a" * 40]


def test_missing_direct_dependency_fails_before_provider():
    root = _task("root", (), agent="root")
    candidate = _task(
        "candidate",
        (CAN_MUTATE_CANDIDATE,),
        deps=("root",),
        agent="builder",
    )
    tasks = {"root": root, "candidate": candidate}
    with pytest.raises(
        TaskDependencyPreconditionFailure,
        match="DEPENDENCY_ARTIFACT_MISSING",
    ) as caught:
        validate_task_dependency_preconditions(
            task=candidate,
            dependency_context={"dependency_results": []},
            task_lookup=tasks.__getitem__,
        )
    assert caught.value.details["provider_call_executed"] is False
