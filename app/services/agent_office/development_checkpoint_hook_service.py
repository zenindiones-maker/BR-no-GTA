from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from app.services.development_checkpoint_capability_service import (
    execute_development_checkpoint_persist_capability,
)
from app.services.harness_authorization_service import issue_harness_authorization


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
    ) -> None:
        self.parent_authorization = parent_authorization
        self.goal_id = str(goal_id)
        self._issue_authorization = issue_authorization
        self._persist_capability = persist_capability
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
        **_: Any,
    ) -> dict[str, Any]:
        key = (str(mission_id), str(task_id), str(recovery_ref))
        ledger = dict(
            self._ledgers.get(key)
            or self._new_ledger(
                mission_id=str(mission_id),
                task_id=str(task_id),
                canonical_branch=str(canonical_branch),
                canonical_base_sha=str(canonical_base_sha),
                recovery_ref=str(recovery_ref),
            )
        )
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
        included_paths = sorted(set(str(p) for p in files_changed if str(p).strip()))
        if not included_paths:
            # A pre-mutation checkpoint still binds the intended bounded write set
            # through the caller-supplied paths when present; an empty baseline is
            # valid and records mission/ledger state without inventing source bytes.
            included_paths = []

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
        result = self._persist_capability(
            authorization=checkpoint_auth,
            repo_root=Path(workspace),
            ledger=ledger,
            checkpoint_request=request,
        )

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
            completed = list(updated.get("completed_steps") or [])
            if checkpoint_event not in completed:
                completed.append(str(checkpoint_event))
            updated["completed_steps"] = completed
            updated["updated_at"] = self._now()
            if checkpoint_event == "AFTER_ATOMIC_TASK_COMPLETION":
                updated["validation_state"] = "TASK_COMPLETE_DURABLE"
                updated["current_step"] = None
                updated["next_step"] = "handoff or candidate derivation"
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
