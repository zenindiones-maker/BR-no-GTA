from __future__ import annotations

from pathlib import Path

import pytest

from app.services.agent_office.development_continuity_boundary import (
    AgentOfficeDevelopmentContinuityBoundary,
    DevelopmentContinuityReceipt,
)
from app.services.development_continuity_guard_service import DevelopmentDurabilityBlocked


def test_mutating_task_requires_baseline_checkpoint_before_worker_mutation(tmp_path: Path):
    calls = []

    def persist(**kwargs):
        calls.append(kwargs)
        return {
            "development_state": "DURABLE",
            "remote_readback_status": "VERIFIED",
            "recovery_commit_sha": "a" * 40,
            "recovery_tree_sha": "b" * 40,
            "checkpoint_id": "cp-1",
            "checkpoint_sequence": 1,
        }

    boundary = AgentOfficeDevelopmentContinuityBoundary(
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="c" * 40,
        mission_id="mission-1",
        workspace_id="agent-office:mission-1",
        recovery_ref="recovery/dev/mission-1",
        persist_checkpoint=persist,
    )

    receipt = boundary.before_first_mutation(
        task_id="task-1",
        workspace=tmp_path,
        included_paths=["app/example.py"],
    )

    assert isinstance(receipt, DevelopmentContinuityReceipt)
    assert receipt.remote_readback_verified is True
    assert calls[0]["checkpoint_event"] == "BEFORE_FIRST_RISKY_MUTATION"
    assert calls[0]["included_paths"] == ["app/example.py"]


def test_terminal_success_blocked_until_remote_checkpoint_readback_verified(tmp_path: Path):
    states = iter([
        {
            "development_state": "DURABLE",
            "remote_readback_status": "VERIFIED",
            "recovery_commit_sha": "a" * 40,
            "recovery_tree_sha": "b" * 40,
            "checkpoint_id": "cp-1",
            "checkpoint_sequence": 1,
        },
        {
            "development_state": "REMOTE_CHECKPOINT_PENDING",
            "remote_readback_status": "PENDING",
            "recovery_commit_sha": "d" * 40,
            "recovery_tree_sha": "e" * 40,
            "checkpoint_id": "cp-2",
            "checkpoint_sequence": 2,
        },
    ])

    boundary = AgentOfficeDevelopmentContinuityBoundary(
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="c" * 40,
        mission_id="mission-2",
        workspace_id="agent-office:mission-2",
        recovery_ref="recovery/dev/mission-2",
        persist_checkpoint=lambda **_: next(states),
    )
    boundary.before_first_mutation(
        task_id="task-2", workspace=tmp_path, included_paths=["app/example.py"]
    )
    with pytest.raises(DevelopmentDurabilityBlocked, match="REMOTE_READBACK_NOT_VERIFIED"):
        boundary.after_atomic_task_completion(
            task_id="task-2",
            workspace=tmp_path,
            included_paths=["app/example.py"],
        )


def test_terminal_receipt_binds_recovery_commit_and_tree(tmp_path: Path):
    calls = []

    def persist(**kwargs):
        calls.append(kwargs)
        seq = len(calls)
        return {
            "development_state": "DURABLE",
            "remote_readback_status": "VERIFIED",
            "recovery_commit_sha": f"{seq}" * 40,
            "recovery_tree_sha": "f" * 40,
            "checkpoint_id": f"cp-{seq}",
            "checkpoint_sequence": seq,
        }

    boundary = AgentOfficeDevelopmentContinuityBoundary(
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="c" * 40,
        mission_id="mission-3",
        workspace_id="agent-office:mission-3",
        recovery_ref="recovery/dev/mission-3",
        persist_checkpoint=persist,
    )
    boundary.before_first_mutation(
        task_id="task-3", workspace=tmp_path, included_paths=["app/example.py"]
    )
    receipt = boundary.after_atomic_task_completion(
        task_id="task-3", workspace=tmp_path, included_paths=["app/example.py"]
    )

    assert receipt.remote_readback_verified is True
    assert receipt.recovery_commit_sha == "2" * 40
    assert receipt.recovery_tree_sha == "f" * 40
    assert calls[-1]["checkpoint_event"] == "AFTER_ATOMIC_TASK_COMPLETION"
