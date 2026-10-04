from __future__ import annotations

from pathlib import Path

from app.services.agent_office.development_checkpoint_hook_service import (
    HarnessDevelopmentCheckpointHook,
)


class ParentAuthorization:
    authorization_id = "parent-auth"
    harness_decision_id = "decision-1"
    execution_id = "execution-1"
    lineage = {"goal_id": "goal-1"}


def test_hook_issues_subordinate_checkpoint_authorization_and_advances_ledger(tmp_path: Path):
    issued = []
    persisted = []

    def issue_auth(**kwargs):
        issued.append(kwargs)
        return type("Auth", (), {"authorization_id": f"cp-auth-{len(issued)}"})()

    def persist_capability(**kwargs):
        persisted.append(kwargs)
        request = kwargs["checkpoint_request"]
        seq = len(persisted)
        return {
            "development_state": "DURABLE",
            "remote_readback_status": "VERIFIED",
            "recovery_commit_sha": str(seq) * 40,
            "recovery_tree_sha": "f" * 40,
            "checkpoint_id": f"cp-{seq}",
            "checkpoint_sequence": seq,
            "content_digest": "d" * 64,
            "progress_ledger": kwargs["ledger"],
        }

    hook = HarnessDevelopmentCheckpointHook(
        parent_authorization=ParentAuthorization(),
        goal_id="goal-1",
        issue_authorization=issue_auth,
        persist_capability=persist_capability,
    )

    first = hook(
        checkpoint_event="BEFORE_FIRST_RISKY_MUTATION",
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="a" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        files_changed=("app/x.py",),
        commits=(),
        candidate={},
    )
    second = hook(
        checkpoint_event="AFTER_ATOMIC_TASK_COMPLETION",
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="a" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        files_changed=("app/x.py",),
        commits=("b" * 40,),
        candidate={"RESULT_COMMIT_SHA": "b" * 40},
    )

    assert first["checkpoint_sha"] == "1" * 40
    assert second["checkpoint_sha"] == "2" * 40
    assert first["remote_readback_status"] == "VERIFIED"
    assert issued[0]["subject"] == "development.checkpoint.persist"
    assert issued[0]["harness_decision_id"] == "decision-1"
    assert issued[0]["execution_id"] == "execution-1"
    assert issued[0]["lineage"]["parent_authorization_id"] == "parent-auth"
    assert persisted[0]["checkpoint_request"]["checkpoint_kind"] == "MILESTONE"
    assert persisted[0]["checkpoint_request"]["included_paths"] == ["app/x.py"]
    assert persisted[1]["ledger"]["checkpoint_sequence"] == 1
    assert persisted[1]["ledger"]["latest_verified_checkpoint_sha"] == "1" * 40
    assert persisted[1]["checkpoint_request"]["expected_previous_remote_oid"] == "1" * 40


def test_hook_does_not_claim_durable_when_capability_readback_is_not_verified(tmp_path: Path):
    def persist_capability(**kwargs):
        return {
            "development_state": "REMOTE_CHECKPOINT_PENDING",
            "remote_readback_status": "PENDING",
            "recovery_commit_sha": "c" * 40,
            "recovery_tree_sha": "d" * 40,
            "checkpoint_id": "cp-1",
            "checkpoint_sequence": 1,
            "content_digest": "e" * 64,
            "progress_ledger": kwargs["ledger"],
        }

    hook = HarnessDevelopmentCheckpointHook(
        parent_authorization=ParentAuthorization(),
        goal_id="goal-1",
        issue_authorization=lambda **_: type("Auth", (), {"authorization_id": "cp-auth"})(),
        persist_capability=persist_capability,
    )
    result = hook(
        checkpoint_event="AFTER_ATOMIC_TASK_COMPLETION",
        workspace=tmp_path,
        mission_id="mission-2",
        task_id="task-2",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="a" * 40,
        recovery_ref="recovery/dev/mission-2/task-2",
        files_changed=("app/y.py",),
        commits=("b" * 40,),
        candidate={},
    )
    assert result["remote_readback_status"] == "PENDING"
