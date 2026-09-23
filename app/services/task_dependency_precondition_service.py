from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.services.capability_execution_contract_service import (
    CAN_MUTATE_CANDIDATE,
    CAN_READ_REPOSITORY,
    CAN_REVIEW,
    CAN_RUN_BENCHMARK,
)


_CANDIDATE_REF_PREFIXES = (
    "git-commit:",
    "candidate-diff:",
    "patch:",
    "diff:",
)


def _is_candidate_artifact_ref(value: str) -> bool:
    text = str(value or "").strip().casefold()
    if not text:
        return False
    if text.startswith(_CANDIDATE_REF_PREFIXES):
        return True
    if not text.startswith("artifact:"):
        return False
    path = text.removeprefix("artifact:")
    return path.endswith((".patch", ".diff")) or "/candidate-" in path and path.endswith(
        (".patch", ".diff", ".json")
    )


@dataclass(frozen=True)
class TaskDependencyPreconditionFailure(RuntimeError):
    code: str
    task_id: str
    dependency_task_id: str | None
    details: dict[str, Any]

    def __str__(self) -> str:
        dep = self.dependency_task_id or "NONE"
        return (
            f"{self.code}:TASK_ID={self.task_id}:"
            f"DEPENDENCY_TASK_ID={dep}:"
            f"DETAILS={self.details}"
        )


def _operations(task: Any) -> set[str]:
    return {
        str(item).strip()
        for item in (getattr(task, "required_operations", ()) or ())
        if str(item).strip()
    }


def _rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = context.get("dependency_results")
    if not isinstance(rows, list):
        rows = context.get("parent_handoffs")
    return [
        dict(item)
        for item in (rows or ())
        if isinstance(item, dict)
    ]


def _artifact_refs(row: dict[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for key in (
        "output_artifact_refs",
        "evidence_refs",
        "metrics_refs",
    ):
        for item in row.get(key) or ():
            text = str(item or "").strip()
            if text and text not in refs:
                refs.append(text)
    return tuple(refs)


def _candidate_refs(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        item
        for item in _artifact_refs(row)
        if _is_candidate_artifact_ref(item)
    )


def _owner(task: Any) -> tuple[str, str, str]:
    return (
        str(getattr(task, "selected_agent_id", "") or ""),
        str(getattr(task, "selected_skill_id", "") or ""),
        str(getattr(task, "capability_id", "") or ""),
    )


def validate_task_dependency_preconditions(
    *,
    task: Any,
    dependency_context: dict[str, Any] | None,
    task_lookup: Callable[[str], Any],
) -> dict[str, Any]:
    ops = _operations(task)
    dependencies = tuple(
        str(item)
        for item in (getattr(task, "dependencies", ()) or ())
        if str(item)
    )
    rows = _rows(dependency_context or {})
    direct = {
        str(item.get("task_id") or ""): item
        for item in rows
        if item.get("direct_dependency") is True
    }

    for dependency in dependencies:
        if dependency not in direct:
            raise TaskDependencyPreconditionFailure(
                code="DEPENDENCY_ARTIFACT_MISSING",
                task_id=str(task.task_id),
                dependency_task_id=dependency,
                details={
                    "expected_artifact_type": "task-result-envelope/v1",
                    "provider_call_executed": False,
                },
            )

    mutating_rows: list[tuple[Any, dict[str, Any]]] = []
    baseline_rows: list[tuple[Any, dict[str, Any]]] = []
    for row in rows:
        source_id = str(row.get("task_id") or "")
        if not source_id:
            continue
        source_task = task_lookup(source_id)
        source_ops = _operations(source_task)
        if CAN_MUTATE_CANDIDATE in source_ops:
            mutating_rows.append((source_task, row))
        if (
            CAN_READ_REPOSITORY in source_ops
            and CAN_MUTATE_CANDIDATE not in source_ops
            and CAN_REVIEW not in source_ops
            and CAN_RUN_BENCHMARK not in source_ops
        ):
            baseline_rows.append((source_task, row))

    candidate_refs = tuple(
        dict.fromkeys(
            ref
            for _source_task, row in mutating_rows
            for ref in _candidate_refs(row)
        )
    )

    if CAN_MUTATE_CANDIDATE in ops:
        missing_payload = [
            dependency
            for dependency in dependencies
            if "result" not in direct[dependency]
        ]
        if missing_payload:
            raise TaskDependencyPreconditionFailure(
                code="CANDIDATE_INPUT_DEPENDENCY_CONTEXT_MISSING",
                task_id=str(task.task_id),
                dependency_task_id=missing_payload[0],
                details={
                    "missing_result_payload": missing_payload,
                    "provider_call_executed": False,
                },
            )

    if CAN_REVIEW in ops and mutating_rows:
        if not candidate_refs:
            raise TaskDependencyPreconditionFailure(
                code="REVIEW_BLOCKED_BY_MISSING_CANDIDATE",
                task_id=str(task.task_id),
                dependency_task_id=str(mutating_rows[-1][0].task_id),
                details={
                    "candidate_artifact_available": False,
                    "provider_call_executed": False,
                },
            )
        reviewer = _owner(task)
        for source_task, _row in mutating_rows:
            if reviewer == _owner(source_task):
                raise TaskDependencyPreconditionFailure(
                    code="REVIEWER_NOT_INDEPENDENT",
                    task_id=str(task.task_id),
                    dependency_task_id=str(source_task.task_id),
                    details={
                        "reviewer": reviewer,
                        "candidate_author": _owner(source_task),
                        "provider_call_executed": False,
                    },
                )

    if CAN_RUN_BENCHMARK in ops and mutating_rows:
        if not candidate_refs:
            raise TaskDependencyPreconditionFailure(
                code="BENCHMARK_BLOCKED_BY_MISSING_CANDIDATE",
                task_id=str(task.task_id),
                dependency_task_id=str(mutating_rows[-1][0].task_id),
                details={
                    "candidate_artifact_available": False,
                    "provider_call_executed": False,
                },
            )
        if not baseline_rows:
            raise TaskDependencyPreconditionFailure(
                code="BENCHMARK_BASELINE_ARTIFACT_MISSING",
                task_id=str(task.task_id),
                dependency_task_id=None,
                details={
                    "baseline_artifact_available": False,
                    "provider_call_executed": False,
                },
            )

    return {
        "status": "PASS",
        "task_id": str(task.task_id),
        "required_operations": sorted(ops),
        "dependency_artifact_count": len(rows),
        "candidate_artifact_refs": list(candidate_refs),
        "baseline_task_ids": [
            str(source_task.task_id)
            for source_task, _row in baseline_rows
        ],
        "provider_call_executed": False,
    }
