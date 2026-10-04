from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from app.services.development_checkpoint_capability_service import (
    execute_development_checkpoint_persist_capability,
)
from app.services.development_recovery_checkpoint_service import (
    DevelopmentRecoveryCheckpointService,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)


def _load_remote_recovery(
    *,
    workspace: Path,
    recovery_ref: str,
    canonical_branch: str,
) -> dict[str, Any]:
    return DevelopmentRecoveryCheckpointService(Path(workspace)).resume(
        recovery_ref,
        canonical_branch=canonical_branch,
    )


class HarnessDevelopmentCheckpointHook:
    """Harness-owned adapter from Agent Office durability events to recovery checkpoints."""

    def __init__(
        self,
        *,
        parent_authorization: Any,
        goal_id: str,
        issue_authorization: Callable[..., Any] = issue_harness_authorization,
        persist_capability: Callable[..., dict[str, Any]] = (
            execute_development_checkpoint_persist_capability
        ),
        recovery_loader: Callable[..., dict[str, Any]] = _load_remote_recovery,
        consume_authorization: Callable[[Any], None] = consume_harness_authorization,
    ) -> None:
        self.parent_authorization = parent_authorization
        self.goal_id = str(goal_id)
        self._issue_authorization = issue_authorization
        self._persist_capability = persist_capability
        self._recovery_loader = recovery_loader
        self._consume_authorization = consume_authorization
        self._ledgers: dict[tuple[str, str, str], dict[str, Any]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _new_ledger(
        self,
        *,
        mission_id: str,
        task_id: str,
        canonical_branch: str,
        canonical_base_sha: str,
        recovery_ref: str,
    ) -> dict[str, Any]:
        goal_digest = sha256(self.goal_id.encode("utf-8")).hexdigest()
        return {
            "schema_version": "DevelopmentProgressLedger/v1",
            "mission_id": mission_id,
            "goal_digest": goal_digest,
            "canonical_branch": canonical_branch,
            "canonical_base_sha": canonical_base_sha,
            "recovery_ref": recovery_ref,
            "latest_verified_checkpoint_id": None,
            "latest_verified_checkpoint_sha": None,
            "checkpoint_sequence": 0,
            "plan_steps": [
                "BEFORE_FIRST_RISKY_MUTATION",
                "AFTER_ATOMIC_TASK_COMPLETION",
            ],
            "completed_steps": [],
            "current_step": "development",
            "next_step": "remote durability checkpoint",
            "open_blockers": [],
            "decisions": [],
            "rejected_directions": [],
            "known_failures": [],
            "validation_state": "IN_PROGRESS",
            "tests": {"state": "NOT_RECORDED"},
            "evidence_refs": [],
            "artifact_refs": [],
            "do_not_repeat": [],
            "side_effects": {
                "known_completed": [],
                "unknown_requires_reconciliation": [],
            },
            "updated_at": self._now(),
        }

    def _load_or_initialize_ledger(
        self,
        *,
        workspace: Path,
        mission_id: str,
        task_id: str,
        canonical_branch: str,
        canonical_base_sha: str,
        recovery_ref: str,
    ) -> dict[str, Any]:
        key = (str(mission_id), str(task_id), str(recovery_ref))
        if key in self._ledgers:
            return dict(self._ledgers[key])

        resumed = dict(
            self._recovery_loader(
                workspace=Path(workspace),
                recovery_ref=str(recovery_ref),
                canonical_branch=str(canonical_branch),
            )
        )
        outcome = str(resumed.get("outcome") or "")
        if outcome == "NO_RECOVERY_STATE":
            return self._new_ledger(
                mission_id=str(mission_id),
                task_id=str(task_id),
                canonical_branch=str(canonical_branch),
                canonical_base_sha=str(canonical_base_sha),
                recovery_ref=str(recovery_ref),
            )
        if outcome != "RESUME_READY":
            raise RuntimeError(f"RECOVERY_RESUME_BLOCKED: {outcome or 'UNKNOWN'}")

        checkpoint = resumed.get("checkpoint")
        if not isinstance(checkpoint, dict):
            raise RuntimeError("RECOVERY_RESUME_BLOCKED: INVALID_CHECKPOINT")
        ledger = checkpoint.get("progress_ledger")
        if not isinstance(ledger, dict):
            raise RuntimeError("RECOVERY_RESUME_BLOCKED: MISSING_PROGRESS_LEDGER")
        if (
            str(ledger.get("mission_id") or "") != str(mission_id)
            or str(ledger.get("recovery_ref") or "") != str(recovery_ref)
            or str(ledger.get("canonical_branch") or "") != str(canonical_branch)
            or str(ledger.get("canonical_base_sha") or "") != str(canonical_base_sha)
        ):
            raise RuntimeError("RECOVERY_RESUME_BLOCKED: LEDGER_IDENTITY_MISMATCH")

        restored = dict(ledger)
        recovery_sha = str(checkpoint.get("recovery_commit_sha") or "")
        checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
        sequence = checkpoint.get("checkpoint_sequence")
        if recovery_sha:
            restored["latest_verified_checkpoint_sha"] = recovery_sha
        if checkpoint_id:
            restored["latest_verified_checkpoint_id"] = checkpoint_id
        if isinstance(sequence, int):
            restored["checkpoint_sequence"] = sequence
        self._ledgers[key] = dict(restored)
        return restored

    def __call__(
        self,
        *,
        checkpoint_event: str,
        workspace: Path,
        mission_id: str,
        task_id: str,
        canonical_branch: str,
        canonical_base_sha: str,
        recovery_ref: str,
        files_changed: tuple[str, ...] = (),
        commits: tuple[str, ...] = (),
        candidate: dict[str, Any] | None = None,
        intended_paths: tuple[str, ...] = (),
        **_: Any,
    ) -> dict[str, Any]:
        key = (str(mission_id), str(task_id), str(recovery_ref))
        ledger = self._load_or_initialize_ledger(
            workspace=Path(workspace),
            mission_id=str(mission_id),
            task_id=str(task_id),
            canonical_branch=str(canonical_branch),
            canonical_base_sha=str(canonical_base_sha),
            recovery_ref=str(recovery_ref),
        )

        completed = list(ledger.get("completed_steps") or [])
        if checkpoint_event not in completed:
            completed.append(str(checkpoint_event))
        ledger["completed_steps"] = completed
        ledger["updated_at"] = self._now()
        if checkpoint_event == "AFTER_ATOMIC_TASK_COMPLETION":
            ledger["validation_state"] = "TASK_COMPLETE_DURABLE"
            ledger["current_step"] = None
            ledger["next_step"] = "handoff or candidate derivation"
        checkpoint_auth = self._issue_authorization(
            authorized_action="DEVELOPMENT",
            subject="development.checkpoint.persist",
            harness_decision_id=self.parent_authorization.harness_decision_id,
            execution_id=self.parent_authorization.execution_id,
            lineage={
                **dict(getattr(self.parent_authorization, "lineage", {}) or {}),
                "parent_authorization_id": self.parent_authorization.authorization_id,
                "parent_subject": getattr(self.parent_authorization, "subject", "capability:agent-office.execute"),
                "capability_id": "development.checkpoint.persist",
                "mission_id": str(mission_id),
                "task_id": str(task_id),
            },
        )
        selected_paths = files_changed or intended_paths
        included_paths = sorted(
            set(str(p) for p in selected_paths if str(p).strip())
        )

        request = {
            "mission_id": str(mission_id),
            "task_id": str(task_id),
            "checkpoint_kind": "MILESTONE",
            "checkpoint_event": str(checkpoint_event),
            "canonical_branch": str(canonical_branch),
            "canonical_base_sha": str(canonical_base_sha),
            "recovery_ref": str(recovery_ref),
            "workspace_id": f"agent-office:{task_id}",
            "sprite_id": None,
            "runtime_namespace": "agent-office",
            "agent_execution_identity": f"agent-office:{task_id}",
            "included_paths": included_paths,
            "excluded_paths": [
                ".env",
                ".secrets",
                "secrets",
                "credentials",
                "assets/private",
                "private",
            ],
            "side_effect_state": {
                "candidate_commits": list(commits),
                "candidate_present": bool(candidate),
            },
            "failure_state": {},
            "resume_instructions": (
                "Restore the verified recovery checkpoint in a fresh workspace; "
                "reconcile canonical before continuing the Agent Office task."
            ),
            "expected_previous_remote_oid": ledger.get(
                "latest_verified_checkpoint_sha"
            ),
        }
        try:
            result = self._persist_capability(
                authorization=checkpoint_auth,
                repo_root=Path(workspace),
                ledger=ledger,
                checkpoint_request=request,
            )
        finally:
            self._consume_authorization(checkpoint_auth)

        verified = (
            str(result.get("development_state") or "") == "DURABLE"
            and str(result.get("remote_readback_status") or "") == "VERIFIED"
        )
        if verified:
            updated = dict(ledger)
            updated["checkpoint_sequence"] = int(result["checkpoint_sequence"])
            updated["latest_verified_checkpoint_id"] = str(result["checkpoint_id"])
            updated["latest_verified_checkpoint_sha"] = str(
                result["recovery_commit_sha"]
            )
            updated["updated_at"] = self._now()
            self._ledgers[key] = updated

        return {
            "checkpoint_sha": str(result.get("recovery_commit_sha") or ""),
            "recovery_ref": str(recovery_ref),
            "remote_readback_status": str(
                result.get("remote_readback_status") or ""
            ),
            "content_digest": str(result.get("content_digest") or ""),
            "recovery_tree_sha": str(result.get("recovery_tree_sha") or ""),
            "checkpoint_id": str(result.get("checkpoint_id") or ""),
            "checkpoint_sequence": result.get("checkpoint_sequence"),
            "development_state": str(result.get("development_state") or ""),
        }
