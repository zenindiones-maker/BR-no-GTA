from __future__ import annotations
from typing import Any

CAN_SEMANTIC_REASONING = "CAN_SEMANTIC_REASONING"
CAN_READ_REPOSITORY = "CAN_READ_REPOSITORY"
CAN_WRITE_REPOSITORY = "CAN_WRITE_REPOSITORY"
CAN_RUN_TESTS = "CAN_RUN_TESTS"
CAN_RUN_BENCHMARK = "CAN_RUN_BENCHMARK"
CAN_MUTATE_CANDIDATE = "CAN_MUTATE_CANDIDATE"
CAN_REVIEW = "CAN_REVIEW"
CAN_CONSUME_ARTIFACT_REFS = "CAN_CONSUME_ARTIFACT_REFS"
CAN_PRODUCE_ARTIFACT_REFS = "CAN_PRODUCE_ARTIFACT_REFS"

ALL_EXECUTION_OPERATIONS = frozenset({
    CAN_SEMANTIC_REASONING,
    CAN_READ_REPOSITORY,
    CAN_WRITE_REPOSITORY,
    CAN_RUN_TESTS,
    CAN_RUN_BENCHMARK,
    CAN_MUTATE_CANDIDATE,
    CAN_REVIEW,
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_PRODUCE_ARTIFACT_REFS,
})

def _blob(requirement: dict[str, Any]) -> str:
    parts = [
        requirement.get("task_id"),
        requirement.get("task_class"),
        requirement.get("objective"),
        requirement.get("query"),
        requirement.get("required_capability_description"),
        requirement.get("expected_output"),
        " ".join(str(x) for x in requirement.get("acceptance_criteria") or ()),
    ]
    return " ".join(str(x or "") for x in parts).casefold()

def derive_required_operations(requirement: dict[str, Any]) -> tuple[str, ...]:
    text = _blob(requirement)
    operations: set[str] = {CAN_PRODUCE_ARTIFACT_REFS}
    dependencies = tuple(requirement.get("dependencies") or ())
    if dependencies:
        operations.add(CAN_CONSUME_ARTIFACT_REFS)

    candidate_markers = (
        "candidate patch", "candidate diff", "patch/diff", "local candidate",
        "candidate commit", "implement candidate", "code candidate",
    )
    benchmark_markers = (
        "benchmark", "baseline_ms", "candidate_ms", "wall clock",
        "latency reduction", "comparison report", "compare baseline",
    )
    review_markers = (
        "independent review", "review verdict", "approve/request-changes",
        "request-changes", "code review",
    )
    profile_markers = (
        "latency profile", "profile", "instrument", "call counts",
        "context sizes", "duplicate-call map", "repository inspection",
    )
    reasoning_markers = (
        "root cause", "analyze", "analysis", "diagnose", "reasoning",
        "causal", "propose",
    )

    if any(marker in text for marker in candidate_markers):
        operations.update({
            CAN_READ_REPOSITORY,
            CAN_WRITE_REPOSITORY,
            CAN_RUN_TESTS,
            CAN_MUTATE_CANDIDATE,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        })
    if any(marker in text for marker in benchmark_markers):
        operations.update({
            CAN_READ_REPOSITORY,
            CAN_RUN_BENCHMARK,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        })
    if any(marker in text for marker in review_markers):
        operations.update({
            CAN_REVIEW,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        })
    if any(marker in text for marker in profile_markers):
        operations.update({
            CAN_READ_REPOSITORY,
            CAN_PRODUCE_ARTIFACT_REFS,
        })
    if any(marker in text for marker in reasoning_markers):
        operations.add(CAN_SEMANTIC_REASONING)

    if operations == {CAN_PRODUCE_ARTIFACT_REFS}:
        operations.add(CAN_SEMANTIC_REASONING)
    return tuple(sorted(operations))

def effective_candidate_requirement(
    declared: str,
    required_operations: tuple[str, ...] | list[str],
) -> str:
    if CAN_MUTATE_CANDIDATE in set(required_operations):
        return "REQUIRED"
    return str(declared or "NOT_APPLICABLE").strip().upper()

def effective_side_effect_class(
    declared: str,
    required_operations: tuple[str, ...] | list[str],
) -> str:
    if CAN_MUTATE_CANDIDATE in set(required_operations):
        return "BOUNDED_MUTATION"
    return str(declared or "READ_ONLY").strip().upper()

def capability_execution_contract_rejection(
    record: Any,
    required_operations: tuple[str, ...] | list[str],
) -> str | None:
    required = {str(x).strip() for x in required_operations if str(x).strip()}
    supported = {
        str(x).strip()
        for x in getattr(record, "execution_operations", ()) or ()
        if str(x).strip()
    }
    missing = sorted(required - supported)
    if missing:
        return "execution-contract-insufficient:missing=" + ",".join(missing)
    return None
