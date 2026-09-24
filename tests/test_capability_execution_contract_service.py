from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_MUTATE_CANDIDATE,
    CAN_READ_REPOSITORY,
    CAN_REVIEW,
    CAN_RUN_BENCHMARK,
    CAN_RUN_TESTS,
    CAN_SEMANTIC_REASONING,
    CAN_PRODUCE_ARTIFACT_REFS,
    CAN_WRITE_REPOSITORY,
    capability_execution_contract_rejection,
    derive_required_operations,
    effective_candidate_requirement,
    effective_side_effect_class,
    execution_kind_rejection,
    infer_functional_role,
    infer_required_execution_kind,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

def _req(task_id, expected_output, *, deps=(), objective=""):
    return {
        "task_id": task_id,
        "task_class": "DEVELOPMENT",
        "action": "DEVELOPMENT",
        "objective": objective,
        "query": objective + " " + expected_output,
        "required_capability_description": objective,
        "dependencies": list(deps),
        "expected_output": expected_output,
        "acceptance_criteria": [expected_output],
    }

def test_profile_task_rejects_semantic_only_addy_and_accepts_repository_profiler():
    ops = derive_required_operations(_req(
        "instrument-baseline",
        "Structured latency profile with call counts, context sizes and duplicate-call map",
        objective="Instrument and profile the semantic planner repository path",
    ))
    assert CAN_READ_REPOSITORY in ops
    addy = GLOBAL_CAPABILITY_REGISTRY.get("addy:planning-and-task-breakdown")
    profiler = GLOBAL_CAPABILITY_REGISTRY.get("agent-office.deterministic-analysis")
    assert "execution-contract-insufficient" in capability_execution_contract_rejection(addy, ops)
    assert capability_execution_contract_rejection(profiler, ops) is None

def test_candidate_requires_real_mutating_executor():
    ops = derive_required_operations(_req(
        "design-candidate",
        "Candidate patch/diff with tests",
        deps=("analyze-root-cause",),
        objective="Implement the minimal isolated candidate fix",
    ))
    assert CAN_MUTATE_CANDIDATE in ops
    assert CAN_CONSUME_ARTIFACT_REFS in ops
    addy = GLOBAL_CAPABILITY_REGISTRY.get("addy:performance-optimization")
    builder = GLOBAL_CAPABILITY_REGISTRY.get("agent-office.codex.bounded-development")
    assert "execution-contract-insufficient" in capability_execution_contract_rejection(addy, ops)
    assert capability_execution_contract_rejection(builder, ops) is None

def test_review_and_benchmark_are_execution_contracts_not_skill_names():
    review_ops = derive_required_operations(_req(
        "independent-review", "Review verdict approve/request-changes", deps=("design-candidate",)
    ))
    benchmark_ops = derive_required_operations(_req(
        "benchmark-compare",
        "Comparison report: baseline_ms, candidate_ms, delta%, quality gate",
        deps=("independent-review",),
    ))
    reviewer = GLOBAL_CAPABILITY_REGISTRY.get("addy:code-review-and-quality")
    semantic_observability = GLOBAL_CAPABILITY_REGISTRY.get("addy:observability-and-instrumentation")
    executor = GLOBAL_CAPABILITY_REGISTRY.get("agent-office.codex.readonly-analysis")
    assert CAN_REVIEW in review_ops
    assert capability_execution_contract_rejection(reviewer, review_ops) is None
    assert CAN_RUN_BENCHMARK in benchmark_ops
    assert "execution-contract-insufficient" in capability_execution_contract_rejection(semantic_observability, benchmark_ops)
    assert capability_execution_contract_rejection(executor, benchmark_ops) is None


def test_legacy_selector_does_not_infer_execution_contract_implicitly():
    from app.services.harness_adaptive_planning_service import (
        select_capability_for_requirement,
    )

    selected, _competence, _avoided, evidence = (
        select_capability_for_requirement(
            {
                "task_id": "legacy-analysis",
                "task_class": "readonly-analysis",
                "action": "DEVELOPMENT",
                "query": "analyze a bounded legacy task",
                "objective": "analyze",
                "candidate_capability_ids": [
                    "system.improvement.propose",
                ],
                "dependencies": [],
                "expected_output": "Evidence",
                "acceptance_criteria": ["evidence"],
                "risk_side_effect_class": "READ_ONLY",
            },
            context={
                "relevant_failure_memories": [],
                "competence_evidence": [],
            },
            used=set(),
        )
    )
    assert selected == "system.improvement.propose"
    assert evidence.get("required_operations") in (None, [])


def test_system_improvement_proposal_has_deterministic_artifact_contract():
    record = GLOBAL_CAPABILITY_REGISTRY.get("system.improvement.propose")
    assert record is not None
    assert record.provider_id == "internal"
    assert CAN_SEMANTIC_REASONING not in record.execution_operations
    assert CAN_CONSUME_ARTIFACT_REFS in record.execution_operations
    assert CAN_PRODUCE_ARTIFACT_REFS in record.execution_operations



def test_semantic_medium_risk_cannot_escalate_readonly_profile_to_mutation():
    requirement = _req(
        "instrument-planner",
        "profiling-report",
        objective=(
            "Profile semantic planner execution to locate redundant context, "
            "duplicate calls, and serial bottlenecks"
        ),
    )
    requirement["risk_side_effect_class"] = "MEDIUM"
    ops = derive_required_operations(requirement)
    assert CAN_READ_REPOSITORY in ops
    assert CAN_WRITE_REPOSITORY not in ops
    assert CAN_MUTATE_CANDIDATE not in ops
    assert effective_candidate_requirement("REQUIRED", ops) == "NOT_APPLICABLE"
    assert effective_side_effect_class("MEDIUM", ops) == "READ_ONLY"


def test_research_content_candidates_do_not_become_repository_mutation():
    requirement = {
        "task_id": "topic-discovery",
        "task_class": "fresh-evidence-collection",
        "action": "RESEARCH",
        "objective": (
            "Produce candidate topics from fresh GTA6 evidence and rank the "
            "strongest current editorial opportunities"
        ),
        "query": "fresh GTA6 candidate topics current evidence",
        "required_capability_description": "fresh evidence topic discovery",
        "dependencies": [],
        "expected_output": "candidate topic shortlist artifact",
        "acceptance_criteria": [
            "candidate topics are grounded in fresh evidence",
        ],
        "risk_side_effect_class": "MEDIUM",
    }
    ops = derive_required_operations(requirement)
    assert CAN_WRITE_REPOSITORY not in ops
    assert CAN_MUTATE_CANDIDATE not in ops
    assert effective_candidate_requirement("REQUIRED", ops) == "NOT_APPLICABLE"
    assert effective_side_effect_class("MEDIUM", ops) == "READ_ONLY"


def test_hyphenated_candidate_output_requires_real_mutation_contract():
    requirement = _req(
        "create-candidate",
        "candidate-patch",
        deps=("instrument-planner",),
        objective=(
            "Implement minimal isolated candidate addressing the identified "
            "bottleneck"
        ),
    )
    requirement["risk_side_effect_class"] = "MEDIUM"
    ops = derive_required_operations(requirement)
    assert CAN_READ_REPOSITORY in ops
    assert CAN_WRITE_REPOSITORY in ops
    assert CAN_MUTATE_CANDIDATE in ops
    assert CAN_RUN_TESTS in ops
    assert effective_candidate_requirement("CONDITIONAL", ops) == "CONDITIONAL"
    assert effective_side_effect_class("MEDIUM", ops) == "BOUNDED_MUTATION"


def test_benchmark_semantic_medium_risk_remains_readonly_execution():
    requirement = _req(
        "validate-candidate",
        "validation-report",
        deps=("create-candidate",),
        objective=(
            "Benchmark candidate vs 14105.371 ms baseline; verify no "
            "quality safety evidence regression"
        ),
    )
    requirement["risk_side_effect_class"] = "MEDIUM"
    ops = derive_required_operations(requirement)
    assert CAN_RUN_BENCHMARK in ops
    assert CAN_WRITE_REPOSITORY not in ops
    assert CAN_MUTATE_CANDIDATE not in ops
    assert effective_candidate_requirement("CONDITIONAL", ops) == "NOT_APPLICABLE"
    assert effective_side_effect_class("MEDIUM", ops) == "READ_ONLY"



def test_system_improvement_roles_have_exact_least_privilege_contracts():
    cases = {
        "EVIDENCE": {
            "task_class": "evidence-collection",
            "expected_output": "IncidentEvidenceBundle",
            "capability_id": "artifact.evidence.reuse",
            "operations": {
                CAN_CONSUME_ARTIFACT_REFS,
                CAN_PRODUCE_ARTIFACT_REFS,
            },
        },
        "DIAGNOSIS": {
            "task_class": "incident-diagnosis",
            "expected_output": "IncidentDiagnosisEvidence",
            "capability_id": "addy:debugging-and-error-recovery",
            "operations": {
                CAN_SEMANTIC_REASONING,
                CAN_CONSUME_ARTIFACT_REFS,
                CAN_PRODUCE_ARTIFACT_REFS,
            },
        },
        "ROOT_CAUSE": {
            "task_class": "root-cause-analysis",
            "expected_output": "RootCauseEvidence",
            "capability_id": "addy:debugging-and-error-recovery",
            "operations": {
                CAN_SEMANTIC_REASONING,
                CAN_CONSUME_ARTIFACT_REFS,
                CAN_PRODUCE_ARTIFACT_REFS,
            },
        },
        "PROPOSAL": {
            "task_class": "recovery-proposal",
            "expected_output": "RecoveryProposalEvidence",
            "capability_id": "addy:debugging-and-error-recovery",
            "operations": {
                CAN_SEMANTIC_REASONING,
                CAN_CONSUME_ARTIFACT_REFS,
                CAN_PRODUCE_ARTIFACT_REFS,
            },
        },
        "REVIEW": {
            "task_class": "independent-review",
            "expected_output": "IndependentReviewEvidence",
            "capability_id": "addy:code-review-and-quality",
            "operations": {
                CAN_REVIEW,
                CAN_SEMANTIC_REASONING,
                CAN_CONSUME_ARTIFACT_REFS,
                CAN_PRODUCE_ARTIFACT_REFS,
            },
        },
        "APPLY": {
            "task_class": "recovery-apply",
            "expected_output": "RecoveryApplyReceipt",
            "capability_id": "harness.recovery.apply-local",
            "operations": {
                CAN_READ_REPOSITORY,
                CAN_WRITE_REPOSITORY,
                CAN_MUTATE_CANDIDATE,
                CAN_CONSUME_ARTIFACT_REFS,
                CAN_PRODUCE_ARTIFACT_REFS,
            },
        },
        "VALIDATE": {
            "task_class": "recovery-validation",
            "expected_output": "RecoveryValidationReceipt",
            "capability_id": "harness.recovery.validate-local",
            "operations": {
                CAN_READ_REPOSITORY,
                CAN_RUN_TESTS,
                CAN_CONSUME_ARTIFACT_REFS,
                CAN_PRODUCE_ARTIFACT_REFS,
            },
        },
    }
    readonly_roles = {
        "EVIDENCE", "DIAGNOSIS", "ROOT_CAUSE", "PROPOSAL", "REVIEW", "VALIDATE"
    }
    deterministic_roles = {"EVIDENCE", "APPLY", "VALIDATE"}
    read_only_role_mutation_requirements = 0
    deterministic_role_semantic_requirements = 0

    for role, expected in cases.items():
        requirement = {
            "task_id": role.casefold().replace("_", "-"),
            "task_class": expected["task_class"],
            "functional_role": role,
            "mission_policy_class": "SYSTEM_IMPROVEMENT",
            "action": "DEVELOPMENT",
            "objective": (
                "candidate patch fix proposal validation evidence review "
                "words must not inflate authority"
            ),
            "query": (
                "candidate patch fix proposal validation evidence review "
                "words must not inflate authority"
            ),
            "required_capability_description": "role contract",
            "dependencies": ["previous"] if role != "EVIDENCE" else [],
            "input_refs": ["artifact:incident.json"],
            "expected_output": expected["expected_output"],
            "acceptance_criteria": ["typed result"],
            "risk_side_effect_class": (
                "BOUNDED_MUTATION" if role == "APPLY" else "READ_ONLY"
            ),
        }
        assert infer_functional_role(requirement) == role
        operations = set(derive_required_operations(requirement))
        assert operations == expected["operations"]
        record = GLOBAL_CAPABILITY_REGISTRY.get(expected["capability_id"])
        assert record is not None
        assert capability_execution_contract_rejection(
            record, tuple(sorted(operations))
        ) is None

        if role in readonly_roles and operations.intersection({
            CAN_WRITE_REPOSITORY,
            CAN_MUTATE_CANDIDATE,
        }):
            read_only_role_mutation_requirements += 1
        if (
            role in deterministic_roles
            and CAN_SEMANTIC_REASONING in operations
        ):
            deterministic_role_semantic_requirements += 1

    assert read_only_role_mutation_requirements == 0
    assert deterministic_role_semantic_requirements == 0


def test_proposal_role_text_cannot_inflate_to_apply_authority():
    requirement = {
        "task_id": "proposal",
        "task_class": "recovery-proposal",
        "functional_role": "PROPOSAL",
        "action": "DEVELOPMENT",
        "objective": (
            "Propose the smallest candidate patch fix and validation tests "
            "without applying repository mutation"
        ),
        "query": "candidate patch fix write modify tests",
        "required_capability_description": "RecoveryProposalEvidence",
        "dependencies": ["root"],
        "expected_output": "RecoveryProposalEvidence",
        "acceptance_criteria": ["safe candidate proposal"],
        "risk_side_effect_class": "READ_ONLY",
    }
    operations = set(derive_required_operations(requirement))
    assert CAN_SEMANTIC_REASONING in operations
    assert CAN_WRITE_REPOSITORY not in operations
    assert CAN_MUTATE_CANDIDATE not in operations
    assert CAN_RUN_TESTS not in operations



def test_analysis_agent_required_rejects_repository_tool_owner():
    requirement = {
        "task_id": "readonly-analysis",
        "task_class": "real-read-only-repository-analysis",
        "action": "DEVELOPMENT",
        "query": "measure repository structure with read-only evidence",
        "objective": "deterministic repository analysis",
        "required_capability_description": "analysis agent",
        "dependencies": [],
        "expected_output": "agent-office-repository-profile/v1",
        "acceptance_criteria": ["measured evidence"],
        "required_operations": [
            CAN_READ_REPOSITORY,
            CAN_PRODUCE_ARTIFACT_REFS,
        ],
        "risk_side_effect_class": "READ_ONLY",
    }
    required_kind = infer_required_execution_kind(requirement)
    assert required_kind == "DETERMINISTIC_ANALYSIS_AGENT"

    analysis_agent = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.deterministic-analysis"
    )
    repository_tool = GLOBAL_CAPABILITY_REGISTRY.get(
        "repository.read-scoped"
    )
    assert analysis_agent is not None
    assert repository_tool is not None
    assert analysis_agent.resolved_execution_kind == (
        "DETERMINISTIC_ANALYSIS_AGENT"
    )
    assert repository_tool.resolved_execution_kind == "TOOL"
    assert execution_kind_rejection(
        analysis_agent,
        required_kind,
    ) is None
    assert "execution-kind-incompatible" in execution_kind_rejection(
        repository_tool,
        required_kind,
    )


def test_selector_filters_tool_before_analysis_agent_ranking():
    from app.services.harness_adaptive_planning_service import (
        select_capability_for_requirement,
    )

    requirement = {
        "task_id": "readonly-analysis",
        "task_class": "real-read-only-repository-analysis",
        "action": "DEVELOPMENT",
        "query": (
            "measure repository structure with deterministic read-only "
            "inspection"
        ),
        "objective": "deterministic repository analysis",
        "required_capability_description": (
            "task-owner repository analysis agent"
        ),
        "candidate_capability_ids": [
            "repository.read-scoped",
            "agent-office.deterministic-analysis",
        ],
        "dependencies": [],
        "expected_output": "agent-office-repository-profile/v1",
        "acceptance_criteria": ["measured repository evidence"],
        "required_operations": [
            CAN_READ_REPOSITORY,
            CAN_PRODUCE_ARTIFACT_REFS,
        ],
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "NOT_APPLICABLE",
    }
    selected, _competence, avoided, evidence = (
        select_capability_for_requirement(
            requirement,
            context={
                "mission_class": "OPEN_SEMANTIC",
                "goal_id": "goal-analysis-kind",
                "domain": "development",
                "task_class": requirement["task_class"],
                "relevant_failure_memories": [],
                "competence_evidence": [],
            },
            used=set(),
        )
    )
    assert selected == "agent-office.deterministic-analysis"
    assert evidence["required_execution_kind"] == (
        "DETERMINISTIC_ANALYSIS_AGENT"
    )
    assert evidence["selected_execution_kind"] == (
        "DETERMINISTIC_ANALYSIS_AGENT"
    )
    assert any(
        item.startswith(
            "repository.read-scoped:execution-kind-incompatible"
        )
        for item in avoided
    )

def test_legacy_implement_role_normalizes_only_for_real_mutation_contracts():
    mutating = {
        "functional_role": "IMPLEMENT",
        "task_class": "bounded-development",
        "required_operations": [
            CAN_WRITE_REPOSITORY,
            CAN_MUTATE_CANDIDATE,
        ],
    }
    assert infer_functional_role(mutating) == "APPLY"

    readonly = {
        "functional_role": "IMPLEMENT",
        "task_class": "readonly-analysis",
        "required_operations": [CAN_READ_REPOSITORY],
    }
    assert infer_functional_role(readonly) == "IMPLEMENT"

def test_editorial_script_review_does_not_require_engineering_independent_reviewer():
    requirement = {
        "task_id": "script-review",
        "functional_role": "REVIEW",
        "task_class": "youtube-script-review",
        "action": "EDITORIAL",
        "objective": "Review the YouTube script against editorial strategy evidence",
        "query": "youtube script review quality evidence",
        "required_capability_description": "independent editorial quality review",
        "dependencies": ["content-strategy"],
        "expected_output": "ScriptReview",
        "acceptance_criteria": ["review references strategy evidence"],
        "risk_side_effect_class": "READ_ONLY",
    }
    ops = derive_required_operations(requirement)
    assert CAN_REVIEW not in ops
    assert CAN_SEMANTIC_REASONING not in ops
    assert infer_required_execution_kind({
        **requirement,
        "required_operations": list(ops),
    }) is None

def test_fact_check_dependency_does_not_inflate_native_executor_to_artifact_io():
    requirement = {
        "task_id": "fact-verify",
        "task_class": "fact-check",
        "action": "RESEARCH",
        "objective": "Verify one selected GTA 6 claim against supplied provenance evidence",
        "query": "fact check verified claim evidence",
        "required_capability_description": "deterministic GTA 6 fact check",
        "dependencies": ["topic-research"],
        "expected_output": "FactCheckResult",
        "acceptance_criteria": ["provenance complete"],
        "risk_side_effect_class": "READ_ONLY",
    }
    assert derive_required_operations(requirement) == ()
    record = GLOBAL_CAPABILITY_REGISTRY.get("gta6.fact-check")
    assert record is not None
    assert capability_execution_contract_rejection(record, ()) is None
