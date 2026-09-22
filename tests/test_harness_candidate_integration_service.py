from __future__ import annotations

from app.services.harness_candidate_integration_service import (
    find_candidate_commit,
    harness_candidate_decision,
    select_independent_reviewer,
    task_is_mutating,
    evaluate_engineering_candidate,
    mission_requires_measured_improvement,
)
from app.services.harness_collaboration_service import (
    TaskEnvelope,
    build_collaboration_plan,
)


def _plan():
    return build_collaboration_plan(
        mission_id="mission-candidate-gate",
        goal_id="goal-candidate-gate",
        tasks=[
            TaskEnvelope(
                task_id="builder",
                capability_id="agent-office.codex.bounded-development",
                action="DEVELOPMENT",
                objective="Create a bounded candidate",
                task_class="bounded-development",
                expected_output="CandidateEvidence",
                read_scope=("app", "tests"),
                write_scope=("app",),
                allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
                acceptance_criteria=("focused tests pass",),
                review_policy="INDEPENDENT_REQUIRED",
                risk_side_effect_class="BOUNDED_MUTATION",
            ),
            TaskEnvelope(
                task_id="reviewer",
                capability_id="agent-office.codex.readonly-analysis",
                action="DEVELOPMENT",
                objective="Review the bounded candidate independently",
                task_class="independent-review",
                dependencies=("builder",),
                expected_output="ReviewEvidence",
                read_scope=("app", "tests"),
                write_scope=(),
                allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
                acceptance_criteria=("review candidate against acceptance criteria",),
                review_policy="NONE",
                risk_side_effect_class="READ_ONLY",
            ),
        ],
    )


def test_generic_candidate_helpers_are_capability_and_contract_driven():
    plan = _plan()
    builder = plan.tasks[0]
    assert task_is_mutating(builder) is True
    reviewer = select_independent_reviewer(plan, "builder")
    assert reviewer is not None
    assert reviewer.task_id == "reviewer"
    assert reviewer.capability_id != builder.capability_id

    sha = "a" * 40
    assert find_candidate_commit({
        "nested": {
            "candidate_commit_sha": sha,
        }
    }) == sha


def test_independent_review_required_fails_closed_before_integration_gate():
    plan = _plan()
    result = evaluate_engineering_candidate(
        repository_root=".",
        base_sha="a" * 40,
        collaboration=plan,
        candidate_task_id="builder",
        candidate_sha="b" * 40,
        reviewed_candidate_ids=(),
    )
    assert result["review_status"] == "MISSING_INDEPENDENT_REVIEW"
    assert result["builder_self_review"] is True
    assert result["gate"]["status"] == "FAIL"
    assert result["gate"]["integration_candidate"] is False
    assert result["gate"]["canonical_push_authority"] == "NONE"


def test_harness_candidate_decision_never_self_promotes():
    rejected = harness_candidate_decision(
        [{
            "builder_self_review": True,
            "gate": {"status": "FAIL"},
        }],
        candidate_required=True,
    )
    assert rejected["decision"] == "REJECT"
    assert rejected["authority"] == "DEEPSEEK_HARNESS"
    assert rejected["agent_self_promotion"] is False
    assert rejected["builder_self_approval"] is False

    accepted_for_human_gate = harness_candidate_decision(
        [{
            "builder_self_review": False,
            "gate": {"status": "PASS"},
        }],
        candidate_required=True,
    )
    assert accepted_for_human_gate["decision"] == "HUMAN_REVIEW"
    assert accepted_for_human_gate["agent_self_promotion"] is False


def test_measured_goal_requires_structured_performance_gate():
    plan = _plan()
    assert mission_requires_measured_improvement(
        "encontre uma perda mensurável e compare antes/depois"
    ) is True
    result = evaluate_engineering_candidate(
        repository_root=".",
        base_sha="a" * 40,
        collaboration=plan,
        candidate_task_id="builder",
        candidate_sha="b" * 40,
        reviewed_candidate_ids=("builder",),
        performance_required=True,
        performance_evidence=None,
    )
    # This candidate cannot reach integration because the fake SHAs are not
    # valid repo commits; the important contract is that performance evidence
    # is required before a real candidate can pass.
    assert result["performance_required"] is True
