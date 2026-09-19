from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.services.agent_office.contracts import AgentOfficeExecutionResult


@dataclass(frozen=True)
class AgentOfficeReduction:
    status: str
    execution_id: str
    task_count: int
    succeeded_count: int
    failed_count: int
    artifact_refs: tuple[dict[str, Any], ...]
    candidate_commits: tuple[str, ...]
    evidence: dict[str, Any]
    integration_results: tuple[dict[str, Any], ...]
    decision_required: str
    authority: str = "DEEPSEEK_HARNESS"
    canonical_push_authority: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _artifact_identity(repository_root: Path, ref: str, expected_sha: str | None) -> dict[str, Any]:
    path = Path(ref)
    if not path.is_absolute():
        path = repository_root / path
    if not path.is_file():
        raise RuntimeError(f"Agent Office artifact missing: {ref}")
    raw = path.read_bytes()
    observed = sha256(raw).hexdigest()
    if expected_sha and observed != expected_sha:
        raise RuntimeError(f"Agent Office artifact hash mismatch: {ref}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Agent Office artifact is not structured JSON: {ref}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Agent Office artifact must contain an object: {ref}")
    return {
        "artifact_ref": ref,
        "sha256": observed,
        "schema_version": 1,
        "producer": payload.get("agent"),
        "task_id": payload.get("task_id"),
        "status": payload.get("status"),
        "short_summary": str(payload.get("summary") or payload.get("error") or "")[:300],
    }


def reduce_agent_office_result(
    *,
    result: AgentOfficeExecutionResult,
    repository_root: str | Path,
    integration_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> AgentOfficeReduction:
    """Reduce task artifacts/evidence before returning control to Harness authority."""
    root = Path(repository_root).resolve()
    identities: list[dict[str, Any]] = []
    candidate_commits: set[str] = set()
    succeeded = 0
    failed = 0
    for item in result.per_agent_results:
        if item.get("status") == "SUCCEEDED":
            succeeded += 1
        else:
            failed += 1
        ref = item.get("artifact_ref")
        if isinstance(ref, str) and ref:
            identities.append(
                _artifact_identity(
                    root,
                    ref,
                    str(item.get("artifact_sha256") or "") or None,
                )
            )
        candidate = item.get("candidate")
        if isinstance(candidate, dict):
            sha = candidate.get("RESULT_COMMIT_SHA")
            if isinstance(sha, str) and sha:
                candidate_commits.add(sha)

    normalized_integrations = tuple(
        {
            "status": str(item.get("status") or "UNKNOWN"),
            "base_sha": item.get("base_sha"),
            "candidate_commit_sha": item.get("candidate_commit_sha"),
            "integration_candidate": bool(item.get("integration_candidate")),
            "canonical_push_authority": item.get("canonical_push_authority"),
            "duration_ms": item.get("duration_ms"),
            "files_changed": list(item.get("files_changed") or ()),
            "conflicts_detected": list(item.get("conflicts_detected") or ()),
        }
        for item in integration_results
    )
    all_integrations_pass = all(
        item["status"] == "PASS"
        and item["integration_candidate"] is True
        and item["canonical_push_authority"] == "NONE"
        for item in normalized_integrations
    )
    if result.status == "SUCCEEDED" and (not candidate_commits or all_integrations_pass):
        status = "READY_FOR_HARNESS_DECISION"
        decision_required = "ACCEPT_OR_PROMOTE_OR_ESCALATE"
    else:
        status = "ESCALATION_REQUIRED"
        decision_required = "REJECT_OR_ESCALATE"

    evidence = {
        "HARNESS_SOLE_AUTHORITY": result.evidence.get("HARNESS_SOLE_AUTHORITY"),
        "HARNESS_MICROMANAGEMENT": result.evidence.get("HARNESS_MICROMANAGEMENT"),
        "WORKTREE_ISOLATION": result.evidence.get("worktree_isolation"),
        "PATH_OWNERSHIP": result.evidence.get("PATH_OWNERSHIP"),
        "CONFLICTS_DETECTED": result.evidence.get("CONFLICTS_DETECTED"),
        "PARALLEL_TASK_COUNT": result.evidence.get("PARALLEL_TASK_COUNT"),
        "SERIAL_TASK_COUNT": result.evidence.get("SERIAL_TASK_COUNT"),
        "PARALLELISM_SAVED_MS": result.evidence.get("PARALLELISM_SAVED_MS"),
        "AGENT_IDLE_MS": result.evidence.get("AGENT_IDLE_MS"),
        "COORDINATION_OVERHEAD_MS": result.evidence.get("COORDINATION_OVERHEAD_MS"),
        "CUMULATIVE_AGENT_WORK_MS": result.evidence.get("CUMULATIVE_AGENT_WORK_MS"),
        "CRITICAL_PATH_MS": result.evidence.get("CRITICAL_PATH_MS"),
        "WALL_CLOCK_MS": result.evidence.get("WALL_CLOCK_MS"),
        "NO_PARALLEL_AUTHORITY": result.evidence.get("no_parallel_authority"),
        "PUBLICATION_AUTHORITY": "NONE",
        "ARTIFACT_FIRST_HANDOFF": "PASS",
    }
    return AgentOfficeReduction(
        status=status,
        execution_id=result.execution_id,
        task_count=len(result.per_agent_results),
        succeeded_count=succeeded,
        failed_count=failed,
        artifact_refs=tuple(identities),
        candidate_commits=tuple(sorted(candidate_commits)),
        evidence=evidence,
        integration_results=normalized_integrations,
        decision_required=decision_required,
    )


def write_reduction_artifact(
    reduction: AgentOfficeReduction,
    path: str | Path,
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(reduction.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(target)
