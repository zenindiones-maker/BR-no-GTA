from __future__ import annotations

from pathlib import Path

import pytest

from app.services.agent_office.munder_adapter import (
    DevelopmentDurabilityAttestationError,
    _require_prewrite_continuity,
)


def _verified(ref: str) -> dict:
    return {
        "checkpoint_sha": "c" * 40,
        "recovery_ref": ref,
        "remote_readback_status": "VERIFIED",
        "content_digest": "d" * 64,
    }


def test_prewrite_continuity_blocks_mutating_task_without_hook(tmp_path: Path):
    with pytest.raises(
        DevelopmentDurabilityAttestationError,
        match="CONTINUITY_NOT_INITIALIZED",
    ):
        _require_prewrite_continuity(
            workspace=tmp_path,
            mission_id="mission-1",
            task_id="task-1",
            canonical_branch="work/gate6f-analytics-learning",
            canonical_base_sha="b" * 40,
            recovery_ref="recovery/dev/mission-1/task-1",
            intended_paths=("app/services/x.py",),
            hook=None,
        )


def test_prewrite_continuity_requires_verified_remote_baseline(tmp_path: Path):
    calls = []

    def hook(**kwargs):
        calls.append(kwargs)
        return {
            **_verified("recovery/dev/mission-1/task-1"),
            "remote_readback_status": "FAILED",
        }

    with pytest.raises(
        DevelopmentDurabilityAttestationError,
        match="REMOTE_READBACK_NOT_VERIFIED",
    ):
        _require_prewrite_continuity(
            workspace=tmp_path,
            mission_id="mission-1",
            task_id="task-1",
            canonical_branch="work/gate6f-analytics-learning",
            canonical_base_sha="b" * 40,
            recovery_ref="recovery/dev/mission-1/task-1",
            intended_paths=("app/services/x.py",),
            hook=hook,
        )
    assert calls[0]["checkpoint_event"] == "BEFORE_FIRST_RISKY_MUTATION"
    assert calls[0]["intended_paths"] == ("app/services/x.py",)


def test_prewrite_continuity_accepts_verified_remote_baseline(tmp_path: Path):
    calls = []

    def hook(**kwargs):
        calls.append(kwargs)
        return _verified("recovery/dev/mission-1/task-1")

    attestation = _require_prewrite_continuity(
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="b" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        intended_paths=("app/services/x.py",),
        hook=hook,
    )
    assert attestation["remote_readback_status"] == "VERIFIED"
    assert calls[0]["checkpoint_event"] == "BEFORE_FIRST_RISKY_MUTATION"
