from __future__ import annotations

from dataclasses import replace

from app.services.agent_office.munder_adapter import MunderAdapter
from tests.test_agent_office_local_degraded_workspace_v2 import (
    _lease,
    _repo,
    _spec,
    _task,
)


def test_mutating_attempts_are_rpo_bounded_and_retry_checkpoints_material_wip(tmp_path):
    root, sha = _repo(tmp_path)
    spec = replace(
        _spec(sha),
        time_budget_seconds=900,
        retry_budget=1,
    )
    task = replace(
        _task(),
        time_budget_seconds=900,
        retry_budget=1,
    )
    lease = replace(
        _lease(sha),
        time_budget_seconds=900,
        retry_budget=1,
    )

    events = []
    timeouts = []
    attempts = {"count": 0}

    def hook(**kwargs):
        events.append(kwargs["checkpoint_event"])
        index = len(events)
        return {
            "checkpoint_sha": f"{index:x}" * 40,
            "recovery_ref": "recovery/dev/mission-preserve/task-preserve",
            "remote_readback_status": "VERIFIED",
            "content_digest": f"{index:x}" * 64,
        }

    def runner(task, workspace, timeout_seconds, lease, repository_root):
        attempts["count"] += 1
        timeouts.append(timeout_seconds)
        target = workspace / "app" / "wip.py"
        if attempts["count"] == 1:
            target.write_text("VALUE = 1\n", encoding="utf-8")
            return {
                "status": "FAILED",
                "error": "recoverable first attempt",
                "recoverable": True,
                "commands": [],
                "tests": [],
                "artifacts": [],
            }
        target.write_text("VALUE = 2\n", encoding="utf-8")
        return {
            "status": "SUCCEEDED",
            "summary": "second attempt succeeded",
            "commands": [],
            "tests": [],
            "artifacts": [],
        }

    result = MunderAdapter(
        worker_runner=runner,
        development_durability_hook=hook,
    ).execute(
        spec,
        (task,),
        root,
        leases={"task-preserve": lease},
    )

    assert result.status == "SUCCEEDED"
    assert attempts["count"] == 2
    assert all(value <= 300 for value in timeouts)
    assert events == [
        "BEFORE_FIRST_RISKY_MUTATION",
        "AFTER_SIGNIFICANT_IMPLEMENTATION",
        "AFTER_ATOMIC_TASK_COMPLETION",
    ]
    item = result.per_agent_results[0]
    assert item["DEVELOPMENT_PROGRESS_DURABLE"] == "PASS"
    assert item["INTERMEDIATE_REMOTE_READBACK"] == "VERIFIED"
    assert result.evidence["LOCAL_DEGRADED_WORKSPACES_PRESERVED"] == 0
