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


def test_system_improvement_proposal_has_explicit_semantic_execution_contract():
    record = GLOBAL_CAPABILITY_REGISTRY.get("system.improvement.propose")
    assert record is not None
    assert CAN_SEMANTIC_REASONING in record.execution_operations
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
