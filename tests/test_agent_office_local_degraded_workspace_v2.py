from __future__ import annotations

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
