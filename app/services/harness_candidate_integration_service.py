from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Sequence

from app.services.agent_office.integration_gate import run_integration_gate


def mission_requires_measured_improvement(human_goal: str) -> bool:
    text = str(human_goal or "").casefold()
    return any(marker in text for marker in (
        "mensur", "measur", "antes/depois", "before/after",
        "compare antes", "performance", "desempenho", "latency",
        "latência", "redund", "benchmark",
    ))


def extract_performance_evidence(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        direct = value.get("performance_evidence")
        if isinstance(direct, dict) and direct.get("evidence_kind") == "MEASURED_BEFORE_AFTER":
            return dict(direct)
        for nested in value.values():
            found = extract_performance_evidence(nested)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = extract_performance_evidence(nested)
            if found is not None:
                return found
    return None


def task_is_mutating(task) -> bool:
    return bool(task.write_scope) or str(
        task.risk_side_effect_class or ""
    ).upper() in {
        "BOUNDED_MUTATION",
        "MUTATING",
        "MEDIUM",
        "HIGH",
    }


def find_candidate_commit(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("RESULT_COMMIT_SHA", "candidate_commit_sha"):
            direct = value.get(key)
            if isinstance(direct, str) and re.fullmatch(r"[0-9a-f]{40}", direct):
                return direct
        commits = value.get("commits")
        if isinstance(commits, (list, tuple)):
            for item in commits:
                if isinstance(item, str) and re.fullmatch(r"[0-9a-f]{40}", item):
                    return item
        for nested in value.values():
            found = find_candidate_commit(nested)
            if found:
                return found
    if isinstance(value, (list, tuple)):
        for nested in value:
            found = find_candidate_commit(nested)
            if found:
                return found
    return None


def select_independent_reviewer(collaboration, candidate_task_id: str):
    candidate = next(
        item for item in collaboration.tasks
        if item.task_id == candidate_task_id
    )
    for reviewer in collaboration.tasks:
        if candidate_task_id not in reviewer.dependencies:
            continue
        if task_is_mutating(reviewer):
            continue
        candidate_identity = (
            candidate.selected_agent_id,
            candidate.selected_skill_id,
            candidate.capability_id,
        )
        reviewer_identity = (
            reviewer.selected_agent_id,
            reviewer.selected_skill_id,
            reviewer.capability_id,
        )
        if reviewer_identity != candidate_identity:
            return reviewer
    return None


def derive_focused_test_commands(
    *,
    repository_root: str | Path,
    base_sha: str,
    candidate_sha: str,
    fallback_tests: Sequence[str] = (
        "tests/test_harness_hermes_delegation_plane.py",
    ),
) -> tuple[tuple[str, ...], ...]:
    root = Path(repository_root).resolve()
    listed = subprocess.check_output(
        [
            "git", "-C", str(root),
            "diff", "--name-only", base_sha, candidate_sha,
        ],
        text=True,
    ).splitlines()
    tests = sorted({
        item for item in listed
        if item.startswith("tests/test_") and item.endswith(".py")
    })
    if not tests:
        tests = list(fallback_tests)
    return tuple(
        ("python", "-m", "pytest", "-q", test_path)
        for test_path in tests
    )


def evaluate_engineering_candidate(
    *,
    repository_root: str | Path,
    base_sha: str,
    collaboration,
    candidate_task_id: str,
    candidate_sha: str,
    reviewed_candidate_ids: Iterable[str],
    performance_evidence: dict[str, Any] | None = None,
    performance_required: bool = False,
    contract_test_commands: Iterable[Sequence[str]] = (
        (
            "python", "-m", "pytest", "-q",
            "tests/test_harness_hermes_delegation_plane.py",
        ),
    ),
    performance_checks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = next(
        item for item in collaboration.tasks
        if item.task_id == candidate_task_id
    )
    if not task_is_mutating(task):
        raise ValueError("candidate task is not mutating")
    if not task.write_scope:
        raise PermissionError(
            "candidate task has no Harness-authorized write scope"
        )

    reviewer = select_independent_reviewer(
        collaboration,
        candidate_task_id,
    )
    builder_identity = (
        task.selected_agent_id,
        task.selected_skill_id,
        task.capability_id,
    )
    reviewer_identity = (
        (
            reviewer.selected_agent_id,
            reviewer.selected_skill_id,
            reviewer.capability_id,
        )
        if reviewer is not None else None
    )
    independent = (
        reviewer_identity is not None
        and reviewer_identity != builder_identity
        and candidate_task_id in set(reviewed_candidate_ids)
    )
    if str(task.review_policy or "").upper() in {
        "INDEPENDENT_REQUIRED",
        "REQUIRED",
    } and not independent:
        return {
            "task_id": candidate_task_id,
            "candidate_sha": candidate_sha,
            "reviewer_task_id": reviewer.task_id if reviewer else None,
            "builder_identity": builder_identity,
            "reviewer_identity": reviewer_identity,
            "builder_self_review": True,
            "review_status": "MISSING_INDEPENDENT_REVIEW",
            "gate": {
                "status": "FAIL",
                "integration_candidate": False,
                "canonical_push_authority": "NONE",
                "security_checks": {
                    "independent_review": "FAIL",
                    "canonical_push_authority": "NONE",
                },
            },
        }

    perf = dict(performance_checks or {})
    perf.setdefault(
        "candidate_has_measurable_acceptance_criteria",
        bool(task.acceptance_criteria),
    )
    if performance_required:
        measured = dict(performance_evidence or {})
        perf["structured_before_after_measurement"] = bool(measured)
        perf["candidate_metric_improved"] = (
            bool(measured.get("improved"))
            and float(measured.get("improvement_delta") or 0.0) > 0.0
        )
        perf["measurement_command_recorded"] = bool(
            str(measured.get("measurement_command") or "").strip()
        )
    gate = run_integration_gate(
        repository_root=repository_root,
        base_sha=base_sha,
        candidate_commit_sha=candidate_sha,
        allowed_paths=tuple(task.write_scope),
        focused_test_commands=derive_focused_test_commands(
            repository_root=repository_root,
            base_sha=base_sha,
            candidate_sha=candidate_sha,
        ),
        contract_test_commands=tuple(contract_test_commands),
        quality_checks={
            "harness_authority_preserved": True,
            "agent_self_promotion": False,
            "independent_review": independent,
        },
        performance_checks=perf,
    ).to_dict()
    return {
        "task_id": candidate_task_id,
        "candidate_sha": candidate_sha,
        "reviewer_task_id": reviewer.task_id if reviewer else None,
        "builder_identity": builder_identity,
        "reviewer_identity": reviewer_identity,
        "builder_self_review": not independent,
        "review_status": "APPROVED" if independent else "NOT_REQUIRED",
        "performance_required": bool(performance_required),
        "performance_evidence": dict(performance_evidence or {}),
        "gate": gate,
    }


def harness_candidate_decision(
    evaluations: Iterable[dict[str, Any]],
    *,
    candidate_required: bool,
) -> dict[str, Any]:
    rows = list(evaluations)
    all_pass = bool(rows) and all(
        item.get("gate", {}).get("status") == "PASS"
        and item.get("builder_self_review") is False
        for item in rows
    )
    decision = (
        "HUMAN_REVIEW"
        if candidate_required and all_pass
        else "REJECT"
        if candidate_required
        else "NOT_REQUIRED"
    )
    return {
        "decision": decision,
        "all_gates_pass": all_pass,
        "candidate_required": candidate_required,
        "authority": "DEEPSEEK_HARNESS",
        "agent_self_promotion": False,
        "builder_self_approval": False,
    }
