from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

from app.services.agent_office.contracts import AgentOfficeExecutionSpec, AgentOfficeTask
from app.services.agent_office.delegation import DelegatedTaskLease, MANDATORY_FORBIDDEN_ACTIONS
from app.services.agent_office.munder_adapter import MunderAdapter


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / "app").mkdir()
    (root / "app" / "base.py").write_text("BASE = 1\n", encoding="utf-8")
    _git(root, "add", "app/base.py")
    _git(root, "commit", "-m", "base")
    return root, _git(root, "rev-parse", "HEAD")


def _spec(sha: str) -> AgentOfficeExecutionSpec:
    return AgentOfficeExecutionSpec.from_mapping(
        {
            "execution_id": "exec-preserve",
            "goal_id": "goal-preserve",
            "brain_decision_id": "decision-preserve",
            "harness_authorization_id": "auth-preserve",
            "authorized_action": "DEVELOPMENT",
            "task_type": "DEVELOPMENT",
            "repository": "zenindiones-maker/BR-no-GTA",
            "branch": "work/gate6f-analytics-learning",
            "base_sha": sha,
            "allowed_agents": ["fake-writer"],
            "allowed_capabilities": ["fake.write"],
            "allowed_paths": ["app"],
            "mission_read_scope": ["app"],
            "mission_write_scope": ["app"],
            "forbidden_actions": sorted(MANDATORY_FORBIDDEN_ACTIONS),
            "max_parallelism": 1,
            "time_budget_seconds": 60,
            "cost_budget": 0,
            "expected_outputs": ["candidate"],
            "evidence_requirements": ["durability"],
            "mission_id": "mission-preserve",
            "delegation_id": "delegation:mission-preserve",
            "allowed_tools": ["git", "python"],
            "allowed_actions": ["edit"],
            "tool_call_budget": 8,
            "retry_budget": 0,
            "acceptance_criteria": ["material WIP is not lost"],
        }
    )


def _task() -> AgentOfficeTask:
    return AgentOfficeTask(
        task_id="task-preserve",
        agent="fake-writer",
        capability="fake.write",
        action="development",
        objective="Mutate one bounded file then fail.",
        allowed_paths=("app",),
        allowed_tools=("git", "python"),
        allowed_actions=("edit",),
        forbidden_actions=tuple(sorted(MANDATORY_FORBIDDEN_ACTIONS)),
        expected_outputs=("candidate",),
        acceptance_criteria=("material WIP is not lost",),
        evidence_requirements=("durability",),
        read_set=("app",),
        write_set=("app",),
        retry_budget=0,
        time_budget_seconds=60,
        cost_budget=0.0,
    )


def _lease(sha: str) -> DelegatedTaskLease:
    task = _task()
    return DelegatedTaskLease(
        mission_id="mission-preserve",
        task_id=task.task_id,
        goal_id="goal-preserve",
        harness_decision_id="decision-preserve",
        authorization_id="auth-preserve",
        delegation_id="delegation:task-preserve",
        agent_id=task.agent,
        capability_ids=(task.capability,),
        base_sha=sha,
        allowed_paths=task.allowed_paths,
        allowed_tools=task.allowed_tools,
        allowed_actions=task.allowed_actions,
        forbidden_actions=task.forbidden_actions,
        input_artifact_refs=(),
        expected_outputs=task.expected_outputs,
        acceptance_criteria=task.acceptance_criteria,
        evidence_requirements=task.evidence_requirements,
        time_budget_seconds=60,
        cost_budget=0.0,
        tool_call_budget=8,
        retry_budget=0,
        max_parallelism=1,
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        escalation_conditions=("durability_failure",),
        owned_task_class="bounded-development",
        role="SPECIALIST_TASK_OWNER",
        read_set=task.read_set,
        write_set=task.write_set,
    )


def test_failed_dirty_writer_preserves_worktree_when_remote_durability_fails(tmp_path: Path):
    root, sha = _repo(tmp_path)
    events = []

    def hook(**kwargs):
        events.append(kwargs["checkpoint_event"])
        if kwargs["checkpoint_event"] == "BEFORE_FIRST_RISKY_MUTATION":
            return {
                "checkpoint_sha": "a" * 40,
                "recovery_ref": "recovery/dev/mission-preserve/task-preserve",
                "remote_readback_status": "VERIFIED",
                "content_digest": "b" * 64,
            }
        raise RuntimeError("remote unavailable")

    def runner(task, workspace, timeout_seconds, lease, repository_root):
        (workspace / "app" / "wip.py").write_text("VALUE = 42\n", encoding="utf-8")
        return {
            "status": "FAILED",
            "error": "simulated writer failure",
            "recoverable": False,
            "commands": [],
            "tests": [],
            "artifacts": [],
        }

    adapter = MunderAdapter(
        worker_runner=runner,
        development_durability_hook=hook,
    )
    result = adapter.execute(
        _spec(sha),
        (_task(),),
        root,
        leases={"task-preserve": _lease(sha)},
    )

    item = result.per_agent_results[0]
    assert item["status"] == "FAILED"
    assert item["PRESERVE_LOCAL_WORKSPACE"] is True
    assert item["DEVELOPMENT_PROGRESS_DURABLE"] == "FAIL"
    preserved = Path(item["PRESERVED_WORKSPACE_PATH"])
    assert preserved.is_dir()
    assert (preserved / "app" / "wip.py").read_text(encoding="utf-8") == "VALUE = 42\n"
    assert str(preserved) in _git(root, "worktree", "list", "--porcelain")
    assert result.evidence["LOCAL_DEGRADED_WORKSPACES_PRESERVED"] == 1
    assert events == ["BEFORE_FIRST_RISKY_MUTATION", "BEFORE_AGENT_HANDOFF"]


def test_worker_exception_after_edit_becomes_typed_failure_and_preserves_workspace(tmp_path: Path):
    root, sha = _repo(tmp_path)

    def hook(**kwargs):
        raise RuntimeError("checkpoint unavailable")

    adapter = MunderAdapter(worker_runner=lambda *_args, **_kwargs: {}, development_durability_hook=hook)

    def explode_after_edit(task, workspace, spec, remaining, lease, repository_root, event_sink):
        (workspace / "app" / "wip.py").write_text("VALUE = 99\n", encoding="utf-8")
        raise RuntimeError("worker exploded after mutation")

    adapter._run_worker = explode_after_edit  # type: ignore[method-assign]
    result = adapter.execute(
        _spec(sha),
        (_task(),),
        root,
        leases={"task-preserve": _lease(sha)},
    )

    assert len(result.per_agent_results) == 1
    item = result.per_agent_results[0]
    assert item["task_id"] == "task-preserve"
    assert item["status"] == "FAILED"
    assert item["failure_class"] == "RuntimeError"
    assert item["PRESERVE_LOCAL_WORKSPACE"] is True
    assert item["LOCAL_ONLY_PROGRESS_DETECTED"] == "YES"
    assert item["DEVELOPMENT_PROGRESS_DURABLE"] == "FAIL"
    preserved = Path(item["PRESERVED_WORKSPACE_PATH"])
    assert (preserved / "app" / "wip.py").read_text(encoding="utf-8") == "VALUE = 99\n"


def _task_named(task_id: str, *, depends_on: tuple[str, ...] = ()) -> AgentOfficeTask:
    return replace(_task(), task_id=task_id, depends_on=depends_on)


def _lease_named(sha: str, task_id: str) -> DelegatedTaskLease:
    return replace(
        _lease(sha),
        task_id=task_id,
        delegation_id=f"delegation:{task_id}",
    )


def test_worker_commit_then_future_exception_attempts_checkpoint_and_records_verified_readback(tmp_path: Path):
    root, sha = _repo(tmp_path)
    checkpoint_calls = []

    def hook(**kwargs):
        checkpoint_calls.append(kwargs)
        return {
            "checkpoint_sha": "c" * 40,
            "recovery_ref": f"recovery/dev/mission-preserve/{kwargs['task_id']}",
            "remote_readback_status": "VERIFIED",
            "content_digest": "d" * 64,
        }

    adapter = MunderAdapter(
        worker_runner=lambda *_args, **_kwargs: {},
        development_durability_hook=hook,
    )

    def explode_after_commit(task, workspace, spec, remaining, lease, repository_root, event_sink):
        (workspace / "app" / "committed.py").write_text("VALUE = 7\n", encoding="utf-8")
        _git(workspace, "add", "app/committed.py")
        _git(workspace, "commit", "-m", "worker partial commit")
        raise RuntimeError("post-commit failure")

    adapter._run_worker = explode_after_commit  # type: ignore[method-assign]
    result = adapter.execute(
        _spec(sha),
        (_task(),),
        root,
        leases={"task-preserve": _lease(sha)},
    )

    item = result.per_agent_results[0]
    assert item["status"] == "FAILED"
    assert item["failure_class"] == "RuntimeError"
    assert item["commits"]
    assert item["DEVELOPMENT_PROGRESS_DURABLE"] == "PASS"
    assert item["REMOTE_READBACK"] == "VERIFIED"
    assert item["PRESERVE_LOCAL_WORKSPACE"] is False
    assert checkpoint_calls
    assert checkpoint_calls[-1]["checkpoint_event"] == "BEFORE_AGENT_HANDOFF"
    assert checkpoint_calls[-1]["commits"]


def test_future_exception_does_not_abort_unrelated_completed_task_collection(tmp_path: Path):
    root, sha = _repo(tmp_path)
    first = _task_named("task-fails")
    second = _task_named("task-succeeds")
    spec = replace(_spec(sha), max_parallelism=2)

    adapter = MunderAdapter(
        worker_runner=lambda *_args, **_kwargs: {},
        development_durability_hook=None,
    )

    def mixed_run(task, workspace, spec, remaining, lease, repository_root, event_sink):
        if task.task_id == "task-fails":
            raise RuntimeError("isolated worker failure")
        return {
            "status": "SUCCEEDED",
            "task_id": task.task_id,
            "agent": task.agent,
            "capability": task.capability,
            "delegation_id": lease.delegation_id,
            "files_changed": [],
            "commits": [],
            "commands": [],
            "tests": [],
            "artifacts": [],
            "task_duration_ms": 1.0,
            "PRESERVE_LOCAL_WORKSPACE": False,
            "LOCAL_ONLY_PROGRESS_DETECTED": "NO",
            "DEVELOPMENT_PROGRESS_DURABLE": "NOT_APPLICABLE",
        }

    adapter._run_worker = mixed_run  # type: ignore[method-assign]
    result = adapter.execute(
        spec,
        (first, second),
        root,
        leases={
            first.task_id: _lease_named(sha, first.task_id),
            second.task_id: _lease_named(sha, second.task_id),
        },
    )

    by_task = {item["task_id"]: item for item in result.per_agent_results}
    assert by_task["task-fails"]["status"] == "FAILED"
    assert by_task["task-fails"]["failure_stage"] == "future_result_exception"
    assert by_task["task-succeeds"]["status"] == "SUCCEEDED"
    assert result.status == "PARTIAL"


def test_no_change_future_exception_is_cleanly_removable_only_after_explicit_clean_inspection(tmp_path: Path):
    root, sha = _repo(tmp_path)
    adapter = MunderAdapter(
        worker_runner=lambda *_args, **_kwargs: {},
        development_durability_hook=None,
    )

    def fail_without_mutation(task, workspace, spec, remaining, lease, repository_root, event_sink):
        raise RuntimeError("failed before mutation")

    adapter._run_worker = fail_without_mutation  # type: ignore[method-assign]
    result = adapter.execute(
        _spec(sha),
        (_task(),),
        root,
        leases={"task-preserve": _lease(sha)},
    )

    item = result.per_agent_results[0]
    assert item["status"] == "FAILED"
    assert item["WORKSPACE_STATE"] == "PROVEN_CLEAN"
    assert item["files_changed"] == []
    assert item["commits"] == []
    assert item["DEVELOPMENT_PROGRESS_DURABLE"] == "NOT_APPLICABLE"
    assert item["PRESERVE_LOCAL_WORKSPACE"] is False
    assert "PRESERVED_WORKSPACE_PATH" not in item


def test_missing_task_result_is_unknown_and_never_force_removed(tmp_path: Path):
    root, sha = _repo(tmp_path)
    cyclic = _task_named("task-cycle", depends_on=("task-cycle",))
    adapter = MunderAdapter(worker_runner=lambda *_args, **_kwargs: {})

    result = adapter.execute(
        _spec(sha),
        (cyclic,),
        root,
        leases={cyclic.task_id: _lease_named(sha, cyclic.task_id)},
    )

    item = next(row for row in result.per_agent_results if row["task_id"] == cyclic.task_id)
    assert item["status"] == "FAILED"
    assert item["failure_class"] == "MissingTaskResult"
    assert item["WORKSPACE_STATE"] == "UNKNOWN"
    assert item["PRESERVE_LOCAL_WORKSPACE"] is True
    preserved = Path(item["PRESERVED_WORKSPACE_PATH"])
    assert preserved.is_dir()
    assert str(preserved) in _git(root, "worktree", "list", "--porcelain")
