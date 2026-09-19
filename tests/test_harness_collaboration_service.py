from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_collaboration_service import build_collaboration_plan


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
