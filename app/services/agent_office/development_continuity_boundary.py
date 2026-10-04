from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from app.services.development_continuity_guard_service import DevelopmentDurabilityBlocked


PersistCheckpoint = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class DevelopmentContinuityReceipt:
    checkpoint_event: str
    checkpoint_id: str
    checkpoint_sequence: int
    recovery_ref: str
    recovery_commit_sha: str
    recovery_tree_sha: str
    remote_readback_verified: bool


class AgentOfficeDevelopmentContinuityBoundary:
    """Fail-closed durability boundary for mutation-capable Agent Office tasks.

    This object deliberately does not grant workers network authority. The caller
    supplies a Harness-governed checkpoint capability adapter; workers only mutate
    their bounded disposable worktree.
    """

    def __init__(
        self,
        *,
        canonical_branch: str,
        canonical_base_sha: str,
        mission_id: str,
        workspace_id: str,
        recovery_ref: str,
        persist_checkpoint: PersistCheckpoint,
    ) -> None:
        self.canonical_branch = str(canonical_branch)
        self.canonical_base_sha = str(canonical_base_sha)
        self.mission_id = str(mission_id)
        self.workspace_id = str(workspace_id)
        self.recovery_ref = str(recovery_ref)
        self._persist_checkpoint = persist_checkpoint
        self._latest_receipt: DevelopmentContinuityReceipt | None = None

    @staticmethod
    def _paths(values: Iterable[str]) -> list[str]:
        return [str(value) for value in values if str(value).strip()]

    def _checkpoint(
        self,
        *,
        checkpoint_event: str,
        task_id: str,
        workspace: Path,
        included_paths: Iterable[str],
    ) -> DevelopmentContinuityReceipt:
        payload = self._persist_checkpoint(
            checkpoint_event=checkpoint_event,
            checkpoint_kind="MILESTONE",
            mission_id=self.mission_id,
            task_id=str(task_id),
            canonical_branch=self.canonical_branch,
            canonical_base_sha=self.canonical_base_sha,
            recovery_ref=self.recovery_ref,
            workspace_id=self.workspace_id,
            repo_root=Path(workspace),
            included_paths=self._paths(included_paths),
        )
        verified = (
            str(payload.get("development_state") or "") == "DURABLE"
            and str(payload.get("remote_readback_status") or "") == "VERIFIED"
        )
        if not verified:
            raise DevelopmentDurabilityBlocked(
                f"REMOTE_READBACK_NOT_VERIFIED: event={checkpoint_event}"
            )
        commit = str(payload.get("recovery_commit_sha") or "")
        tree = str(payload.get("recovery_tree_sha") or "")
        checkpoint_id = str(payload.get("checkpoint_id") or "")
        sequence = payload.get("checkpoint_sequence")
        if len(commit) != 40 or len(tree) != 40 or not checkpoint_id:
            raise DevelopmentDurabilityBlocked(
                f"INVALID_REMOTE_CHECKPOINT_RECEIPT: event={checkpoint_event}"
            )
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise DevelopmentDurabilityBlocked(
                f"INVALID_CHECKPOINT_SEQUENCE: event={checkpoint_event}"
            )
        receipt = DevelopmentContinuityReceipt(
            checkpoint_event=checkpoint_event,
            checkpoint_id=checkpoint_id,
            checkpoint_sequence=sequence,
            recovery_ref=self.recovery_ref,
            recovery_commit_sha=commit,
            recovery_tree_sha=tree,
            remote_readback_verified=True,
        )
        self._latest_receipt = receipt
        return receipt

    def before_first_mutation(
        self,
        *,
        task_id: str,
        workspace: Path,
        included_paths: Iterable[str],
    ) -> DevelopmentContinuityReceipt:
        return self._checkpoint(
            checkpoint_event="BEFORE_FIRST_RISKY_MUTATION",
            task_id=task_id,
            workspace=workspace,
            included_paths=included_paths,
        )

    def after_atomic_task_completion(
        self,
        *,
        task_id: str,
        workspace: Path,
        included_paths: Iterable[str],
    ) -> DevelopmentContinuityReceipt:
        return self._checkpoint(
            checkpoint_event="AFTER_ATOMIC_TASK_COMPLETION",
            task_id=task_id,
            workspace=workspace,
            included_paths=included_paths,
        )

    @property
    def latest_receipt(self) -> DevelopmentContinuityReceipt | None:
        return self._latest_receipt
