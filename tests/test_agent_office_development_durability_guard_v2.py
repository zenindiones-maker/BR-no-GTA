from __future__ import annotations

from pathlib import Path

from app.services.agent_office.munder_adapter import (
    DevelopmentDurabilityAttestationError,
    _enforce_material_result_durability,
)


def _result() -> dict:
    return {
        "status": "SUCCEEDED",
        "files_changed": ["app/services/x.py"],
        "commits": ["a" * 40],
        "candidate": {"RESULT_COMMIT_SHA": "a" * 40},
    }


def test_material_success_without_durability_hook_is_blocked(tmp_path: Path):
    result = _result()
    _enforce_material_result_durability(
        result=result,
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="b" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        hook=None,
    )
    assert result["status"] == "BLOCKED"
    assert result["error"] == "DEVELOPMENT_DURABILITY_BLOCKED"
    assert result["LOCAL_ONLY_PROGRESS_DETECTED"] == "YES"
    assert result["DEVELOPMENT_PROGRESS_DURABLE"] == "FAIL"


def test_material_success_requires_verified_remote_readback(tmp_path: Path):
    result = _result()

    def hook(**_kwargs):
        return {
            "checkpoint_sha": "c" * 40,
            "recovery_ref": "recovery/dev/mission-1/task-1",
            "remote_readback_status": "FAILED",
            "content_digest": "d" * 64,
        }

    _enforce_material_result_durability(
        result=result,
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="b" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        hook=hook,
    )
    assert result["status"] == "BLOCKED"
    assert result["DEVELOPMENT_PROGRESS_DURABLE"] == "FAIL"


def test_material_success_accepts_exact_verified_remote_checkpoint(tmp_path: Path):
    result = _result()
    calls = []

    def hook(**kwargs):
        calls.append(kwargs)
        return {
            "checkpoint_sha": "c" * 40,
            "recovery_ref": "recovery/dev/mission-1/task-1",
            "remote_readback_status": "VERIFIED",
            "content_digest": "d" * 64,
        }

    _enforce_material_result_durability(
        result=result,
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="b" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        hook=hook,
    )
    assert result["status"] == "SUCCEEDED"
    assert result["LOCAL_ONLY_PROGRESS_DETECTED"] == "NO"
    assert result["DEVELOPMENT_PROGRESS_DURABLE"] == "PASS"
    assert result["REMOTE_READBACK"] == "VERIFIED"
    assert result["RECOVERY_CHECKPOINT_SHA"] == "c" * 40
    assert calls[0]["checkpoint_event"] == "AFTER_ATOMIC_TASK_COMPLETION"


def test_readonly_success_does_not_require_development_checkpoint(tmp_path: Path):
    result = {"status": "SUCCEEDED", "files_changed": [], "commits": []}
    _enforce_material_result_durability(
        result=result,
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="b" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        hook=None,
    )
    assert result["status"] == "SUCCEEDED"
    assert result["DEVELOPMENT_PROGRESS_DURABLE"] == "NOT_APPLICABLE"


def test_failed_material_work_is_checkpointed_before_handoff(tmp_path: Path):
    result = {
        "status": "FAILED",
        "error": "worker failed after mutation",
        "files_changed": ["app/services/x.py"],
        "commits": [],
    }
    calls = []

    def hook(**kwargs):
        calls.append(kwargs)
        return {
            "checkpoint_sha": "c" * 40,
            "recovery_ref": "recovery/dev/mission-1/task-1",
            "remote_readback_status": "VERIFIED",
            "content_digest": "d" * 64,
        }

    _enforce_material_result_durability(
        result=result,
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="b" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        hook=hook,
    )
    assert result["status"] == "FAILED"
    assert result["DEVELOPMENT_PROGRESS_DURABLE"] == "PASS"
    assert result["LOCAL_ONLY_PROGRESS_DETECTED"] == "NO"
    assert calls[0]["checkpoint_event"] == "BEFORE_AGENT_HANDOFF"


def test_failed_material_work_marks_local_durability_failure_when_checkpoint_fails(tmp_path: Path):
    result = {
        "status": "FAILED",
        "error": "worker failed after mutation",
        "files_changed": ["app/services/x.py"],
        "commits": [],
    }

    def hook(**_kwargs):
        raise RuntimeError("remote unavailable")

    _enforce_material_result_durability(
        result=result,
        workspace=tmp_path,
        mission_id="mission-1",
        task_id="task-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="b" * 40,
        recovery_ref="recovery/dev/mission-1/task-1",
        hook=hook,
    )
    assert result["status"] == "FAILED"
    assert result["DEVELOPMENT_PROGRESS_DURABLE"] == "FAIL"
    assert result["LOCAL_ONLY_PROGRESS_DETECTED"] == "YES"
    assert result["PRESERVE_LOCAL_WORKSPACE"] is True
