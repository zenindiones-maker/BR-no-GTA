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
    normalized_text = text.replace("-", " ").replace("_", " ")
    operations: set[str] = {CAN_PRODUCE_ARTIFACT_REFS}
    dependencies = tuple(requirement.get("dependencies") or ())
    if dependencies:
        operations.add(CAN_CONSUME_ARTIFACT_REFS)

    candidate_markers = (
        "candidate patch",
        "candidate diff",
        "patch diff",
        "local candidate",
        "candidate commit",
        "code candidate",
    )
    candidate_action_markers = (
        "implement",
        "create",
        "build",
        "produce",
        "apply",
        "write",
        "modify",
        "change",
        "fix",
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
        "causal", "propose", "synthesize", "synthesis", "interpret",
    )
    deterministic_evidence_classes = {
        "evidence-collection",
        "fresh-evidence-collection",
        "knowledge-retrieval",
        "fact-check",
        "source-verification",
    }
    deterministic_evidence_markers = (
        "collect fresh evidence",
        "collect evidence",
        "evidence collection",
        "retrieve knowledge",
        "knowledge retrieval",
        "fact-check",
        "fact check",
        "source verification",
        "source packet",
    )

    task_class = str(requirement.get("task_class") or "").strip().casefold()
    candidate_mutation = (
        task_class in {"bounded-development", "adaptive-code-change"}
        or any(marker in normalized_text for marker in candidate_markers)
        or (
            "candidate" in normalized_text
            and any(
                marker in normalized_text
                for marker in candidate_action_markers
            )
        )
    )
    if candidate_mutation:
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

    deterministic_evidence_task = (
        task_class in deterministic_evidence_classes
        or any(marker in normalized_text for marker in deterministic_evidence_markers)
    )
    if (
        operations == {CAN_PRODUCE_ARTIFACT_REFS}
        and not deterministic_evidence_task
    ):
        operations.add(CAN_SEMANTIC_REASONING)
    return tuple(sorted(operations))

def effective_candidate_requirement(
    declared: str,
    required_operations: tuple[str, ...] | list[str],
) -> str:
    operations = set(required_operations)
    if CAN_MUTATE_CANDIDATE in operations:
        normalized = str(declared or "REQUIRED").strip().upper()
        return (
            normalized
            if normalized in {"REQUIRED", "CONDITIONAL"}
            else "REQUIRED"
        )
    return "NOT_APPLICABLE"

def effective_side_effect_class(
    declared: str,
    required_operations: tuple[str, ...] | list[str],
) -> str:
    operations = set(required_operations)
    if (
        CAN_MUTATE_CANDIDATE in operations
        or CAN_WRITE_REPOSITORY in operations
    ):
        return "BOUNDED_MUTATION"
    return "READ_ONLY"

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
