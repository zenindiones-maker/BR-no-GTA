from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Sequence


_GITHUB_OPERATIONAL_STATES = {
    "requested": "CREATED_NOT_YET_QUEUED",
    "queued": "QUEUED_FOR_RUNNER",
    "pending": "WAITING_FOR_CONCURRENCY",
    "waiting": "WAITING_FOR_ENVIRONMENT_OR_PROTECTION",
    "in_progress": "EXECUTING",
    "completed": "TERMINAL_GITHUB_RUN",
}
_TERMINAL_OUTCOMES = {
    "success": "SUCCESS",
    "failure": "FAILURE",
    "timed_out": "FAILURE_TIMEOUT",
    "action_required": "EXTERNAL_ACTION_STATE",
    "cancelled": "CANCELLED",
    "stale": "NON_PROVING_STALE",
    "skipped": "NON_PROVING_SKIPPED",
    "neutral": "NON_PROVING",
}


@dataclass(frozen=True)
class GitHubActionsRunStatus:
    run_id: int
    status: str
    conclusion: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and self.conclusion == "success"

    @property
    def failed(self) -> bool:
        return (
            self.status == "completed"
            and self.conclusion in {"failure", "timed_out", "action_required"}
        )

    @property
    def cancelled(self) -> bool:
        return self.status == "completed" and self.conclusion == "cancelled"

    @property
    def operational_state(self) -> str:
        return _GITHUB_OPERATIONAL_STATES.get(
            self.status,
            "UNKNOWN_GITHUB_RUN_STATE",
        )


@dataclass(frozen=True)
class GitHubActionsProofObservation:
    run_id: int
    status: str
    conclusion: str | None
    head_sha: str
    workflow: str
    branch: str
    run_attempt: int | None
    evidence_valid: bool = True


@dataclass(frozen=True)
class GitHubActionsProofClassification:
    raw_status: str
    raw_conclusion: str | None
    operational_state: str
    proof_relevance: str
    proof_result: str
    terminal_outcome: str | None
    current_head_proven: bool
    mission_failure: bool
    reason: str


def classify_github_actions_proof(
    observation: GitHubActionsProofObservation,
    *,
    remote_head: str,
    expected_workflow: str,
    expected_branch: str,
    evidence_required: bool = False,
) -> GitHubActionsProofClassification:
    status = str(observation.status or "").strip().lower()
    conclusion = (
        str(observation.conclusion).strip().lower()
        if observation.conclusion is not None
        else None
    )
    operational = _GITHUB_OPERATIONAL_STATES.get(
        status, "UNKNOWN_GITHUB_RUN_STATE"
    )
    head_matches = bool(remote_head) and observation.head_sha == remote_head
    scoped = (
        head_matches
        and observation.workflow == expected_workflow
        and observation.branch == expected_branch
        and isinstance(observation.run_attempt, int)
        and not isinstance(observation.run_attempt, bool)
        and observation.run_attempt > 0
    )
    if head_matches:
        relevance = "CURRENT_HEAD"
    elif status == "completed" and conclusion in {"cancelled", "stale"}:
        relevance = "SUPERSEDED"
    else:
        relevance = "HISTORICAL"

    if status == "requested":
        proof_result = "NOT_STARTED"
    elif status in {"queued", "pending", "waiting"}:
        proof_result = "WAITING"
    elif status == "in_progress":
        proof_result = "EXECUTING"
    elif status != "completed":
        proof_result = "NON_PROVING"
    elif conclusion in {"failure", "timed_out"}:
        proof_result = "FAIL"
    elif conclusion == "success":
        evidence_ok = observation.evidence_valid or not evidence_required
        proof_result = "PASS" if scoped and evidence_ok else "NON_PROVING"
    else:
        proof_result = "NON_PROVING"

    proven = proof_result == "PASS"
    terminal = _TERMINAL_OUTCOMES.get(conclusion) if status == "completed" else None
    mission_failure = (
        relevance == "CURRENT_HEAD"
        and status == "completed"
        and conclusion in {"failure", "timed_out"}
    )
    if proven:
        reason = "exact current-head workflow/ref/attempt proof succeeded"
    elif relevance == "SUPERSEDED":
        reason = "older SHA execution was superseded by a newer remote HEAD"
    elif status == "pending":
        reason = "GitHub run is waiting for concurrency serialization"
    elif status == "waiting":
        reason = "GitHub run is waiting for environment/protection"
    elif status == "completed" and conclusion == "success":
        reason = "successful run is not an exact current-head proof"
    else:
        reason = "GitHub execution evidence is non-authoritative for mission terminality"
    return GitHubActionsProofClassification(
        raw_status=status,
        raw_conclusion=conclusion,
        operational_state=operational,
        proof_relevance=relevance,
        proof_result=proof_result,
        terminal_outcome=terminal,
        current_head_proven=proven,
        mission_failure=mission_failure,
        reason=reason,
    )


CommandRunner = Callable[[Sequence[str]], str]


class GitHubActionsRunTracker:
    def __init__(self, command_runner: CommandRunner) -> None:
        if command_runner is None:
            raise ValueError("O executor de comandos GitHub é obrigatório.")
        self.command_runner = command_runner

    def get_status(self, repository: str, run_id: int) -> GitHubActionsRunStatus:
        if not repository:
            raise ValueError("O repositório GitHub é obrigatório.")
        if not isinstance(run_id, int) or run_id <= 0:
            raise ValueError("O run_id GitHub deve ser um inteiro positivo.")
        command = [
            "gh", "run", "view", str(run_id), "--repo", repository,
            "--json", "status,conclusion",
        ]
        output = self.command_runner(command)
        if not output:
            raise RuntimeError(
                "O GitHub Actions não retornou o estado do workflow run."
            )
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "A resposta do GitHub Actions não é um JSON válido."
            ) from exc
        status = payload.get("status")
        conclusion = payload.get("conclusion")
        if not status:
            raise RuntimeError(
                "A resposta do GitHub Actions não contém o status do run."
            )
        return GitHubActionsRunStatus(
            run_id=run_id,
            status=str(status),
            conclusion=str(conclusion) if conclusion is not None else None,
        )
