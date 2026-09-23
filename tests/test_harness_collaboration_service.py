from app.services import harness_collaboration_service as collaboration_service
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_collaboration_service import (
    build_collaboration_plan,
    build_goal_envelope,
)


def test_collaboration_plan_routes_real_specialists_and_handoffs():
    plan = build_collaboration_plan(
        mission_id="mission-real-synergy-contract",
        goal_id="goal-real-synergy-contract",
        tasks=[
            {
                "task_id": "fact-check",
                "capability_id": "gta6.fact-check",
                "action": "RESEARCH",
                "objective": "verify GTA6 claims from observed source evidence",
                "input_refs": ["research:observed"],
                "expected_output": "FactCheckResult",
            },
            {
                "task_id": "content-strategy",
                "capability_id": "youtube.department.content-strategy",
                "action": "EDITORIAL",
                "objective": "derive a grounded content angle from verified claims",
                "dependencies": ["fact-check"],
                "input_refs": ["fact-check:verified"],
                "expected_output": "YouTubeSpecialistResult",
            },
            {
                "task_id": "production-management",
                "capability_id": "youtube.department.production-management",
                "action": "EXECUTION",
                "objective": "review production readiness without dispatching production",
                "dependencies": ["content-strategy"],
                "input_refs": ["strategy:grounded"],
                "expected_output": "YouTubeSpecialistResult",
            },
        ],
    )

    assert plan.authority == "DEEPSEEK_HARNESS"
    assert plan.execution_levels == (
        ("fact-check",),
        ("content-strategy",),
        ("production-management",),
    )
    assert [task.capability_id for task in plan.tasks] == [
        "gta6.fact-check",
        "youtube.department.content-strategy",
        "youtube.department.production-management",
    ]
    assert all(task.routing_id for task in plan.tasks)
    assert all(task.selected_executor_binding for task in plan.tasks)
    assert plan.tasks[1].selected_agent_id == "tubegent-content-strategy"
    assert plan.tasks[2].selected_agent_id == "tubegent-production-management"


def test_collaboration_plan_rejects_cycles():
    try:
        build_collaboration_plan(
            mission_id="mission-cycle",
            goal_id="goal-cycle",
            tasks=[
                {
                    "task_id": "a",
                    "capability_id": "gta6.fact-check",
                    "action": "RESEARCH",
                    "objective": "a",
                    "dependencies": ["b"],
                },
                {
                    "task_id": "b",
                    "capability_id": "youtube.department.content-strategy",
                    "action": "EDITORIAL",
                    "objective": "b",
                    "dependencies": ["a"],
                },
            ],
        )
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("cyclic collaboration graph was accepted")


def test_tubegent_and_improvement_are_in_global_registry():
    for capability_id in (
        "youtube.department.content-strategy",
        "youtube.department.script-review",
        "youtube.department.seo",
        "youtube.department.thumbnail-strategy",
        "youtube.department.production-management",
        "youtube.department.publishing-policy",
        "youtube.department.analytics-analysis",
        "youtube.department.monetization-analysis",
        "youtube.department.optimization",
        "youtube.monetization.observe",
        "system.improvement.propose",
    ):
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None, capability_id
        assert record.available is True
        assert record.executor_binding
        assert record.evidence_contract



def test_provider_runtime_incident_is_system_improvement_even_with_gta6_subject():
    goal = build_goal_envelope(
        human_goal=(
            "Diagnose and recover the real runtime provider incident for "
            "gta6.research.semantic-synthesis without changing the GTA6 product goal."
        ),
        project="BR-no-GTA",
        goal_id="goal-provider-incident",
        subject="BR-no-GTA real provider incident recovery",
        source_surface="github-actions-control",
    )
    assert goal.mission_class == "SYSTEM_IMPROVEMENT"



def test_system_improvement_selection_requirement_normalizes_action_without_losing_declared_semantics():
    goal = build_goal_envelope(
        human_goal="Diagnose and recover a provider runtime incident.",
        project="BR-no-GTA",
        goal_id="goal-system-action-policy",
        subject="provider incident recovery",
        source_surface="github-actions-control",
    )
    requirement = {
        "task_id": "collect-evidence",
        "task_class": "evidence-collection",
        "action": "RESEARCH",
        "objective": "collect observed incident evidence",
        "dependencies": [],
        "expected_output": "EvidencePacket",
        "required_operations": [
            "CAN_CONSUME_ARTIFACT_REFS",
            "CAN_PRODUCE_ARTIFACT_REFS",
        ],
    }
    normalized = collaboration_service._selection_requirement_for_mission(
        goal,
        requirement,
    )
    assert goal.mission_class == "SYSTEM_IMPROVEMENT"
    assert normalized["declared_action"] == "RESEARCH"
    assert normalized["declared_task_class"] == "evidence-collection"
    assert normalized["action"] == "DEVELOPMENT"
    assert normalized["task_class"] == "system-improvement"
    assert normalized["mission_action_normalized"] is True
    assert requirement["action"] == "RESEARCH"
    assert requirement["task_class"] == "evidence-collection"



def test_independent_review_contract_is_enriched_before_registry_selection():
    goal = build_goal_envelope(
        human_goal="Diagnose and recover a provider runtime incident with independent review.",
        project="BR-no-GTA",
        goal_id="goal-review-contract",
        subject="provider incident recovery",
        source_surface="github-actions-control",
    )
    requirement = {
        "task_id": "review-recovery",
        "task_class": "independent-review",
        "action": "DEVELOPMENT",
        "objective": "Independently review the recovery proposal.",
        "required_capability_description": "independent semantic engineering review",
        "dependencies": ["proposal"],
        "expected_output": "INDEPENDENT_REVIEW_ARTIFACT",
        "required_operations": [
            "CAN_SEMANTIC_REASONING",
            "CAN_CONSUME_ARTIFACT_REFS",
            "CAN_PRODUCE_ARTIFACT_REFS",
        ],
        "risk_side_effect_class": "READ_ONLY",
    }
    normalized = collaboration_service._selection_requirement_for_mission(
        goal,
        requirement,
    )
    assert normalized["review_contract_enriched"] is True
    assert set(normalized["required_operations"]) >= {
        "CAN_REVIEW",
        "CAN_SEMANTIC_REASONING",
        "CAN_CONSUME_ARTIFACT_REFS",
        "CAN_PRODUCE_ARTIFACT_REFS",
    }
    assert normalized["action"] == "DEVELOPMENT"
    assert normalized["task_class"] == "system-improvement"
    assert "CAN_REVIEW" not in requirement["required_operations"]
