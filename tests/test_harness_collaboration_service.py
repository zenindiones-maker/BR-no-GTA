from app.services.harness_collaboration_service import plan_mission_from_human_goal
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
    assert normalized["task_class"] == "evidence-collection"
    assert normalized["mission_policy_class"] == "SYSTEM_IMPROVEMENT"
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
    assert normalized["task_class"] == "independent-review"
    assert normalized["mission_policy_class"] == "SYSTEM_IMPROVEMENT"
    assert "CAN_REVIEW" not in requirement["required_operations"]



def test_editorial_script_review_keeps_editorial_contract_without_engineering_review_inflation():
    goal = build_goal_envelope(
        human_goal="Revisa o roteiro e melhora a estratégia editorial.",
        project="BR-no-GTA",
        goal_id="goal-editorial-review-contract",
        subject="script:8",
    )
    requirement = {
        "task_id": "review-script",
        "task_class": "youtube-script-review",
        "action": "EDITORIAL",
        "objective": "independent editorial quality review of the YouTube script",
        "required_capability_description": "independent editorial quality review",
        "dependencies": ["strategy"],
        "expected_output": "ScriptReview",
        "acceptance_criteria": ["review references strategy evidence"],
        "risk_side_effect_class": "READ_ONLY",
    }
    normalized = collaboration_service._selection_requirement_for_mission(
        goal,
        requirement,
    )
    assert goal.mission_class == "EDITORIAL"
    assert normalized["action"] == "EDITORIAL"
    assert normalized["task_class"] == "youtube-script-review"
    assert normalized["review_contract_enriched"] is False
    assert normalized["mission_action_normalized"] is False
    assert "CAN_REVIEW" not in set(
        normalized.get("required_operations") or ()
    )


def test_system_improvement_independent_review_still_enriches_engineering_review_contract():
    goal = build_goal_envelope(
        human_goal="Diagnose and recover a provider runtime incident with independent review.",
        project="BR-no-GTA",
        goal_id="goal-system-independent-review-contract",
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
        "expected_output": "IndependentReviewEvidence",
        "risk_side_effect_class": "READ_ONLY",
    }
    normalized = collaboration_service._selection_requirement_for_mission(
        goal,
        requirement,
    )
    assert normalized["action"] == "DEVELOPMENT"
    assert normalized["task_class"] == "independent-review"
    assert normalized["mission_policy_class"] == "SYSTEM_IMPROVEMENT"
    assert normalized["review_contract_enriched"] is True
    assert set(normalized["required_operations"]) >= {
        "CAN_REVIEW",
        "CAN_SEMANTIC_REASONING",
        "CAN_CONSUME_ARTIFACT_REFS",
        "CAN_PRODUCE_ARTIFACT_REFS",
    }



def test_real_incident_recovery_uses_typed_read_only_dag_before_semantic_planner():
    goal = build_goal_envelope(
        human_goal=(
            "Diagnose o incidente real, encontre a causa raiz, proponha a menor "
            "recovery e faça review independente sem aplicar mutation."
        ),
        project="BR-no-GTA",
        goal_id="goal-real-incident-recovery",
        subject="provider/runtime incident recovery",
        source_surface="github-actions-control",
        canonical_state={
            "incident": {
                "source_run_id": 35898595164,
                "task_id": "production-planning",
                "observed_error": (
                    "no healthy Registry capability for "
                    "task_class=production-planning"
                ),
            },
            "incident_evidence_artifact_ref": (
                "artifact:incident-evidence-packet.json"
            ),
            "mutation_policy": (
                "NO_MUTATION_BEFORE_AGENT_DIAGNOSIS_REVIEW_HARNESS_DECISION"
            ),
        },
    )
    requirements = (
        collaboration_service._deterministic_incident_recovery_requirements(
            goal
        )
    )

    assert [item["functional_role"] for item in requirements] == [
        "EVIDENCE", "DIAGNOSIS", "ROOT_CAUSE", "PROPOSAL", "REVIEW",
    ]
    assert [item["task_class"] for item in requirements] == [
        "evidence-collection",
        "incident-diagnosis",
        "root-cause-analysis",
        "recovery-proposal",
        "independent-review",
    ]
    assert [item["task_id"] for item in requirements] == [
        "task-01", "task-02", "task-03", "task-04", "task-05",
    ]
    assert set(requirements[0]["required_operations"]) == {
        "CAN_CONSUME_ARTIFACT_REFS",
        "CAN_PRODUCE_ARTIFACT_REFS",
    }
    assert requirements[0]["risk_side_effect_class"] == "READ_ONLY"
    assert requirements[0]["input_refs"] == [
        "artifact:incident-evidence-packet.json"
    ]
    for item in requirements[1:4]:
        assert set(item["required_operations"]) == {
            "CAN_CONSUME_ARTIFACT_REFS",
            "CAN_PRODUCE_ARTIFACT_REFS",
            "CAN_SEMANTIC_REASONING",
        }
        assert item["candidate_requirement"] == "NOT_APPLICABLE"
    assert set(requirements[4]["required_operations"]) == {
        "CAN_REVIEW",
        "CAN_SEMANTIC_REASONING",
        "CAN_CONSUME_ARTIFACT_REFS",
        "CAN_PRODUCE_ARTIFACT_REFS",
    }
    assert all(
        item["risk_side_effect_class"] == "READ_ONLY"
        for item in requirements
    )
    assert all(
        "CAN_WRITE_REPOSITORY" not in set(item["required_operations"])
        and "CAN_MUTATE_CANDIDATE" not in set(item["required_operations"])
        for item in requirements
    )
    assert [item["dependencies"] for item in requirements] == [
        [], ["task-01"], ["task-02"], ["task-03"], ["task-04"],
    ]


def test_incident_recovery_plan_does_not_call_semantic_planner(monkeypatch):
    goal = build_goal_envelope(
        human_goal=(
            "Diagnose and recover the real internal provider/runtime incident "
            "with independent review."
        ),
        project="BR-no-GTA",
        goal_id="goal-no-semantic-planner",
        subject="real provider incident recovery",
        source_surface="github-actions-control",
        canonical_state={
            "incident": {
                "source_run_id": 35898595164,
                "task_id": "production-planning",
                "capability_id": "harness.semantic-mission-planner",
                "observed_error": "planner contract selection failure",
            },
            "incident_evidence_artifact_ref": (
                "artifact:incident-evidence-packet.json"
            ),
            "mutation_policy": (
                "NO_MUTATION_BEFORE_AGENT_DIAGNOSIS_REVIEW_HARNESS_DECISION"
            ),
        },
    )
    from app.services.provider_health_service import semantic_provider_health
    health = semantic_provider_health()
    if not bool(health.get("semantic_reasoning_available")):
        requirements = (
            collaboration_service._deterministic_incident_recovery_requirements(
                goal
            )
        )
        for requirement in requirements:
            required_operations = set(
                requirement["required_operations"]
            )
            compatible = [
                record
                for record in (
                    collaboration_service.GLOBAL_CAPABILITY_REGISTRY.all()
                )
                if record.execution_enabled is True
                and requirement["action"] in set(record.allowed_actions)
                and required_operations.issubset(
                    set(record.execution_operations)
                )
                and str(record.side_effect_class).upper() == "READ_ONLY"
            ]
            assert compatible, (
                requirement["task_id"],
                requirement["functional_role"],
                sorted(required_operations),
            )
        return

    monkeypatch.setattr(
        collaboration_service,
        "propose_validated_semantic_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "semantic planner must not run for typed incident recovery"
            )
        ),
    )

    plan = collaboration_service.plan_mission_from_human_goal(
        goal,
        artifact_ref="artifact:incident-evidence-packet.json",
    )

    assert plan.planning_mode == "DETERMINISTIC_INCIDENT_RECOVERY"
    assert plan.planning_evidence["semantic_provider_call_count"] == 0
    tasks = list(plan.collaboration_plan.tasks)
    assert len(tasks) == 5
    assert [task.task_class for task in tasks] == [
        "evidence-collection",
        "incident-diagnosis",
        "root-cause-analysis",
        "recovery-proposal",
        "independent-review",
    ]
    assert [task.functional_role for task in tasks] == [
        "EVIDENCE", "DIAGNOSIS", "ROOT_CAUSE", "PROPOSAL", "REVIEW",
    ]
    assert all(
        task.mission_policy_class == "SYSTEM_IMPROVEMENT"
        for task in tasks
    )
    assert tasks[0].capability_id == "artifact.evidence.reuse"
    assert tasks[0].selected_agent_id == "artifact-lineage-worker"
    assert tasks[0].required_operations == (
        "CAN_PRODUCE_ARTIFACT_REFS",
    )
    assert all(task.risk_side_effect_class == "READ_ONLY" for task in tasks)
    assert all(
        "CAN_WRITE_REPOSITORY" not in set(task.required_operations)
        and "CAN_MUTATE_CANDIDATE" not in set(task.required_operations)
        for task in tasks
    )
    selections = plan.planning_evidence["selection"]
    assert [item["task_class"] for item in selections] == [
        "evidence-collection",
        "incident-diagnosis",
        "root-cause-analysis",
        "recovery-proposal",
        "independent-review",
    ]
    assert all(
        item["discovery_order_functional_weight"] == 0.0
        for item in selections
    )
    assert all(
        item["least_privilege_selection"] is True
        for item in selections
    )
    assert all(
        candidate["score_components"]["registry_discovery"] == 0.0
        for item in selections
        for candidate in item["top_candidates"]
    )
    review = tasks[-1]
    proposal = tasks[-2]
    assert (
        review.selected_agent_id != proposal.selected_agent_id
        or review.selected_skill_id != proposal.selected_skill_id
    )



def test_sandboxed_recovery_policy_keeps_incident_planning_deterministic():
    goal = build_goal_envelope(
        human_goal=(
            "Diagnose the real incident, review the bounded recovery and "
            "allow sandboxed mutation only after ACCEPT + Harness decision."
        ),
        project="BR-no-GTA",
        goal_id="goal-sandboxed-recovery-policy",
        subject="provider/runtime incident recovery",
        source_surface="github-actions-control",
        canonical_state={
            "incident": {
                "source_run_id": 35898595164,
                "task_id": "production-planning",
                "observed_error": (
                    "no healthy Registry capability for "
                    "task_class=production-planning"
                ),
            },
            "incident_evidence_artifact_ref": (
                "artifact:incident-evidence-packet.json"
            ),
            "mutation_policy": (
                "ALLOW_SANDBOXED_MUTATION_ONLY_AFTER_ACCEPT_REVIEW_"
                "AND_HARNESS_AUTHORIZATION"
            ),
        },
    )

    requirements = (
        collaboration_service._deterministic_incident_recovery_requirements(
            goal
        )
    )

    assert [item["functional_role"] for item in requirements] == [
        "EVIDENCE",
        "DIAGNOSIS",
        "ROOT_CAUSE",
        "PROPOSAL",
        "REVIEW",
    ]
    assert all(item["action"] == "DEVELOPMENT" for item in requirements)
    assert all(
        "CAN_WRITE_REPOSITORY"
        not in set(item["required_operations"])
        for item in requirements
    )
    assert all(
        "CAN_MUTATE_CANDIDATE"
        not in set(item["required_operations"])
        for item in requirements
    )
    assert "CAN_SEMANTIC_REASONING" not in set(
        requirements[0]["required_operations"]
    )
    assert "CAN_SEMANTIC_REASONING" in set(
        requirements[3]["required_operations"]
    )


def test_private_production_boundary_resolves_missing_downstream_capability_question():
    goal = build_goal_envelope(
        human_goal=(
            "Produza um novo vídeo real do BR no GTA 6 e leve o master aprovado "
            "somente para revisão privada no YouTube."
        ),
        project="BR-no-GTA",
        goal_id="goal-private-production-boundary",
        subject="real multi-agent GTA6 audiovisual production",
        source_surface="work",
        canonical_state={
            "youtube_publication_public": "FORBIDDEN",
            "youtube_publication_unlisted": "FORBIDDEN",
            "youtube_private_hd_review": "ALLOWED",
            "human_goal_execution_authorized": True,
            "semantic_planning_boundary": (
                "PREPRODUCTION_THROUGH_PRODUCTION_PLAN"
            ),
            "downstream_execution_orchestrated_by_workflow": True,
        },
    )
    question = (
        "No runtime/render/narration capability is present in the provided "
        "capabilities list, and YouTube private upload capability is also missing. "
        "Should the plan rely on production.plan to represent downstream steps or "
        "require explicit capability addition?"
    )

    assert collaboration_service._clarification_is_resolved_by_explicit_goal(
        goal,
        question,
    ) is True


def test_missing_downstream_capability_question_is_not_suppressed_without_boundary():
    goal = build_goal_envelope(
        human_goal="Prepare a GTA6 research plan.",
        project="BR-no-GTA",
        goal_id="goal-no-production-boundary",
        subject="GTA6 research",
        source_surface="work",
        canonical_state={
            "human_goal_execution_authorized": True,
        },
    )
    question = (
        "No runtime/render/narration capability is present in the provided "
        "capabilities list. Should the plan require explicit capability addition?"
    )

    assert collaboration_service._clarification_is_resolved_by_explicit_goal(
        goal,
        question,
    ) is False

def _durable_identity_proposal(*, task_id: str, objective: str) -> dict:
    return {
        "interpreted_goal": "Improve safely",
        "assumptions": [],
        "required_outcomes": ["proof"],
        "tasks": [{
            "task_id": task_id,
            "objective": objective,
            "task_class": "analysis",
            "required_capability_description": "repository analysis",
            "candidate_capability_ids": [],
            "dependencies": [],
            "expected_output": "Evidence",
            "acceptance_criteria": ["proof"],
            "risk_side_effect_class": "READ_ONLY",
            "action": "RESEARCH",
        }],
        "rationale": "identity regression proof",
        "context_usage_notes": [],
        "uncertainty": 0.1,
        "needs_human_clarification": False,
        "clarification_question": None,
        "memory_strategy_notes": [],
        "reused_artifact_refs": [],
        "avoided_bad_paths": [],
    }


def test_durable_mission_identity_is_not_derived_from_plan_content(monkeypatch):
    goal = build_goal_envelope(
        human_goal="Improve system safely",
        project="BR-no-GTA",
        goal_id="goal-stable-mission",
        subject="system improvement",
    )
    identity = {
        "mission_id": "mission-stable",
        "human_goal_id": "goal-stable-mission",
        "lineage_id": "lineage-stable",
    }
    monkeypatch.setattr(
        collaboration_service,
        "propose_validated_semantic_plan",
        lambda _context, *, inference=None, max_replans=1: (
            type("SemanticResult", (), {
                "proposal": collaboration_service.MissionPlanProposal.from_dict(
                    inference("", {}) if inference else {}
                )
            })(),
            {
                "proposal_attempts": 1,
                "replan_count": 0,
                "provider_evidence": {"test_fixture": True},
            },
        ),
    )
    monkeypatch.setattr(
        collaboration_service,
        "select_capability_for_requirement",
        lambda requirement, **kwargs: (
            "repository.read-scoped",
            False,
            [],
            {"selection_source": "identity-test-fixture"},
        ),
    )
    p1 = plan_mission_from_human_goal(
        goal,
        trusted_mission_identity=identity,
        semantic_inference=lambda *_: _durable_identity_proposal(
            task_id="t1",
            objective="inspect repository state",
        ),
    )
    p2 = plan_mission_from_human_goal(
        goal,
        trusted_mission_identity=identity,
        semantic_inference=lambda *_: _durable_identity_proposal(
            task_id="t2",
            objective="inspect a different repository boundary",
        ),
    )
    assert p1.mission_id == "mission-stable"
    assert p2.mission_id == "mission-stable"
    assert p1.plan_id != p2.plan_id
    assert p1.tasks != p2.tasks


def test_durable_mission_identity_invalid_fails_before_semantic_inference():
    goal = build_goal_envelope(
        human_goal="Improve system safely",
        project="BR-no-GTA",
        goal_id="goal-a",
        subject="system improvement",
    )
    calls = {"semantic": 0}
    def should_never_run(*_args, **_kwargs):
        calls["semantic"] += 1
        raise AssertionError("SEMANTIC_INFERENCE_MUST_NOT_RUN")
    import pytest
    with pytest.raises(ValueError, match="DURABLE_MISSION_IDENTITY_INVALID"):
        plan_mission_from_human_goal(
            goal,
            trusted_mission_identity={
                "mission_id": "",
                "human_goal_id": "goal-a",
                "lineage_id": "l",
            },
            semantic_inference=should_never_run,
        )
    assert calls["semantic"] == 0


def test_durable_mission_identity_goal_mismatch_fails_closed():
    goal = build_goal_envelope(
        human_goal="Improve system safely",
        project="BR-no-GTA",
        goal_id="goal-a",
        subject="system improvement",
    )
    calls = {"semantic": 0}
    def should_never_run(*_args, **_kwargs):
        calls["semantic"] += 1
        raise AssertionError("SEMANTIC_INFERENCE_MUST_NOT_RUN")
    import pytest
    with pytest.raises(ValueError, match="DURABLE_MISSION_HUMAN_GOAL_MISMATCH"):
        plan_mission_from_human_goal(
            goal,
            trusted_mission_identity={
                "mission_id": "m",
                "human_goal_id": "goal-b",
                "lineage_id": "l",
            },
            semantic_inference=should_never_run,
        )
    assert calls["semantic"] == 0
