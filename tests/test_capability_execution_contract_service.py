from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_MUTATE_CANDIDATE,
    CAN_READ_REPOSITORY,
    CAN_REVIEW,
    CAN_RUN_BENCHMARK,
    capability_execution_contract_rejection,
    derive_required_operations,
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
    profiler = GLOBAL_CAPABILITY_REGISTRY.get("agent-office.deterministic.readonly-analysis")
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
