from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.agent_office.development_checkpoint_hook_service import (
    HarnessDevelopmentCheckpointHook,
)


def _parent():
    return SimpleNamespace(
        authorization_id="parent-auth",
        harness_decision_id="decision-1",
        execution_id="exec-1",
        subject="capability:agent-office.execute",
        lineage={"goal_id": "goal-1"},
    )


def _durable_result(seq: int, sha: str) -> dict:
    return {
        "development_state": "DURABLE",
        "remote_readback_status": "VERIFIED",
        "recovery_commit_sha": sha,
        "recovery_tree_sha": ("f" if sha[0] != "f" else "e") * 40,
        "content_digest": str(seq) * 64,
        "checkpoint_id": f"cp-{seq}",
        "checkpoint_sequence": seq,
    }


def test_hook_issues_checkpoint_auth_and_checkpoints_intended_write_set(tmp_path: Path):
    issued = []
    persisted = []

    def issue(**kwargs):
        issued.append(kwargs)
        return SimpleNamespace(authorization_id=f"checkpoint-auth-{len(issued)}")

    def persist(**kwargs):
        persisted.append(kwargs)
        return _durable_result(len(persisted), "c" * 40 if len(persisted) == 1 else "d" * 40)

    hook = HarnessDevelopmentCheckpointHook(
        parent_authorization=_parent(),
        goal_id="goal-1",
        issue_authorization=issue,
        persist_capability=persist,
        recovery_loader=lambda **_: {"outcome": "NO_RECOVERY_STATE"},
    )

    first = hook(
        checkpoint_event="BEFORE_FIRST_RISKY_MUTATION",
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="a" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        intended_paths=("app/services/x.py", "tests/test_x.py"),
    )
    assert first["remote_readback_status"] == "VERIFIED"
    assert issued[0]["subject"] == "development.checkpoint.persist"
    assert issued[0]["lineage"]["parent_authorization_id"] == "parent-auth"
    assert persisted[0]["checkpoint_request"]["included_paths"] == [
        "app/services/x.py",
        "tests/test_x.py",
    ]
    assert persisted[0]["checkpoint_request"]["expected_previous_remote_oid"] is None

    second = hook(
        checkpoint_event="AFTER_ATOMIC_TASK_COMPLETION",
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="a" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        files_changed=("app/services/x.py",),
        commits=("b" * 40,),
        candidate={"RESULT_COMMIT_SHA": "b" * 40},
    )
    assert second["checkpoint_sha"] == "d" * 40
    assert persisted[1]["ledger"]["checkpoint_sequence"] == 1
    assert persisted[1]["ledger"]["latest_verified_checkpoint_sha"] == "c" * 40
    assert persisted[1]["checkpoint_request"]["expected_previous_remote_oid"] == "c" * 40


def test_fresh_hook_resumes_remote_ledger_before_next_checkpoint(tmp_path: Path):
    persisted = []

    remote_ledger = {
        "schema_version": "DevelopmentProgressLedger/v1",
        "mission_id": "mission-1",
        "goal_digest": "1" * 64,
        "canonical_branch": "work/gate6f-analytics-learning",
        "canonical_base_sha": "a" * 40,
        "recovery_ref": "recovery/dev/mission-1/task-1",
        "latest_verified_checkpoint_id": "cp-4",
        "latest_verified_checkpoint_sha": "e" * 40,
        "checkpoint_sequence": 4,
        "plan_steps": ["BEFORE_FIRST_RISKY_MUTATION", "AFTER_ATOMIC_TASK_COMPLETION"],
        "completed_steps": ["BEFORE_FIRST_RISKY_MUTATION"],
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
        "side_effects": {"known_completed": [], "unknown_requires_reconciliation": []},
        "updated_at": "2026-10-04T12:00:00+00:00",
    }

    def load(**_kwargs):
        return {
            "outcome": "RESUME_READY",
            "checkpoint": {
                "recovery_commit_sha": "e" * 40,
                "progress_ledger": remote_ledger,
            },
        }

    def persist(**kwargs):
        persisted.append(kwargs)
        return _durable_result(5, "f" * 40)

    hook = HarnessDevelopmentCheckpointHook(
        parent_authorization=_parent(),
        goal_id="goal-1",
        issue_authorization=lambda **_: SimpleNamespace(authorization_id="checkpoint-auth"),
        persist_capability=persist,
        recovery_loader=load,
    )
    result = hook(
        checkpoint_event="AFTER_ATOMIC_TASK_COMPLETION",
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="a" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        files_changed=("app/services/x.py",),
    )
    assert result["checkpoint_sequence"] == 5
    assert persisted[0]["ledger"]["checkpoint_sequence"] == 4
    assert persisted[0]["checkpoint_request"]["expected_previous_remote_oid"] == "e" * 40


def test_fresh_hook_fails_closed_when_remote_recovery_requires_reconciliation(tmp_path: Path):
    hook = HarnessDevelopmentCheckpointHook(
        parent_authorization=_parent(),
        goal_id="goal-1",
        issue_authorization=lambda **_: SimpleNamespace(authorization_id="checkpoint-auth"),
        persist_capability=lambda **_: pytest.fail("persist must not run"),
        recovery_loader=lambda **_: {
            "outcome": "RECONCILIATION_REQUIRED",
            "canonical_head": "9" * 40,
        },
    )
    with pytest.raises(RuntimeError, match="RECOVERY_RESUME_BLOCKED"):
        hook(
            checkpoint_event="BEFORE_FIRST_RISKY_MUTATION",
            workspace=tmp_path,
            mission_id="mission-1",
            task_id="task-1",
            canonical_branch="work/gate6f-analytics-learning",
            canonical_base_sha="a" * 40,
            recovery_ref="recovery/dev/mission-1/task-1",
            intended_paths=("app/services/x.py",),
        )
