from __future__ import annotations

from pathlib import Path
import subprocess
import threading
import time

import pytest

from app.database.agent_execution_lease_repository import get_lease, list_task_events
from app.database.schema import initialize_schema
from app.services.agent_office.contracts import AgentOfficeExecutionSpec, AgentOfficeTask
from app.services.agent_office.delegation import DelegatedTaskLease, write_conflicts
from app.services.agent_office.integration_gate import detect_candidate_conflicts, run_integration_gate
from app.services.agent_office.munder_adapter import MunderAdapter
from app.services.agent_office.service import AgentOfficeService
from app.services.harness_authorization_service import issue_harness_authorization


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "delegation@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Delegation Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/zenindiones-maker/BR-no-GTA.git"],
        cwd=root, check=True,
    )
    (root / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=root, check=True, capture_output=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return root, sha


def _authorized_spec(root: Path, sha: str, *, max_parallelism: int = 3):
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject="capability:agent-office.execute",
        harness_decision_id="delegated-canary-decision",
        execution_id="delegated-canary-execution",
        lineage={"goal_id": "delegated-canary-goal"},
    )
    spec = AgentOfficeExecutionSpec.from_mapping(
        {
            "execution_id": authorization.execution_id,
            "mission_id": "delegated-canary-mission",
            "delegation_id": "delegation:delegated-canary-mission",
            "goal_id": "delegated-canary-goal",
            "brain_decision_id": authorization.harness_decision_id,
            "harness_authorization_id": authorization.authorization_id,
            "authorized_action": "DEVELOPMENT",
            "task_type": "DELEGATED_AUTONOMY_CANARY",
            "repository": "zenindiones-maker/BR-no-GTA",
            "branch": "main",
            "base_sha": sha,
            "allowed_agents": ["specialist"],
            "allowed_capabilities": ["repository.read"],
            "allowed_paths": ["a.txt", "b.txt", "README.md"],
            "allowed_tools": ["git", "python", "pytest"],
            "allowed_actions": ["analyze", "inspect", "test", "benchmark", "edit", "commit_candidate"],
            "forbidden_actions": ["youtube_publish", "autonomous_schedule"],
            "max_parallelism": max_parallelism,
            "time_budget_seconds": 30,
            "cost_budget": 0,
            "tool_call_budget": 16,
            "retry_budget": 1,
            "expected_outputs": ["analysis"],
            "acceptance_criteria": ["structured evidence returned"],
            "evidence_requirements": ["artifact_ref", "commands"],
        }
    )
    return authorization, spec


def _task(task_id: str, write_set: list[str] | None = None, depends_on: list[str] | None = None):
    return AgentOfficeTask.from_mapping(
        {
            "task_id": task_id,
            "agent": "specialist",
            "capability": "repository.read",
            "action": "analyze",
            "objective": f"Analyze {task_id}",
            "owned_task_class": "CANARY_ANALYSIS",
            "role": "SPECIALIST_TASK_OWNER",
            "allowed_paths": ["a.txt", "b.txt", "README.md"],
            "allowed_tools": ["git"],
            "allowed_actions": ["analyze"],
            "read_set": ["README.md"],
            "write_set": write_set or [],
            "depends_on": depends_on or [],
            "tool_call_budget": 4,
            "retry_budget": 1,
            "expected_outputs": ["analysis"],
            "acceptance_criteria": ["task completes"],
            "evidence_requirements": ["commands"],
        }
    )


def test_delegated_lease_rejects_authority_expansion():
    with pytest.raises(ValueError, match="mandatory boundaries"):
        DelegatedTaskLease.from_mapping(
            {
                "mission_id": "m", "task_id": "t", "goal_id": "g",
                "harness_decision_id": "d", "authorization_id": "a",
                "delegation_id": "delegation:m:t", "agent_id": "x",
                "capability_ids": ["repository.read"], "base_sha": "a" * 40,
                "allowed_paths": [], "allowed_tools": ["git"], "allowed_actions": ["analyze"],
                "forbidden_actions": ["push"], "input_artifact_refs": [],
                "expected_outputs": ["analysis"], "acceptance_criteria": ["ok"],
                "evidence_requirements": ["commands"], "time_budget_seconds": 10,
                "cost_budget": 0, "tool_call_budget": 2, "retry_budget": 0,
                "max_parallelism": 1, "expires_at": "2099-01-01T00:00:00+00:00",
                "escalation_conditions": ["scope_change"], "owned_task_class": "ANALYSIS",
                "role": "TASK_OWNER", "read_set": [], "write_set": [],
            }
        )


def test_write_conflicts_and_candidate_conflicts_are_deterministic():
    base = {
        "mission_id": "m", "goal_id": "g", "harness_decision_id": "d",
        "authorization_id": "a", "agent_id": "x", "capability_ids": ["repository.read"],
        "base_sha": "a" * 40, "allowed_paths": ["app"], "allowed_tools": ["git"],
        "allowed_actions": ["edit"], "forbidden_actions": sorted({
            "push","merge","canonical_branch_write","policy_mutation","authority_mutation",
            "secret_access","credential_access","destructive_database_migration",
            "external_paid_action","youtube_publish_public",
        }), "input_artifact_refs": [], "expected_outputs": ["candidate"],
        "acceptance_criteria": ["ok"], "evidence_requirements": ["diff"],
        "time_budget_seconds": 10, "cost_budget": 0, "tool_call_budget": 2,
        "retry_budget": 0, "max_parallelism": 2,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "escalation_conditions": ["conflict"], "owned_task_class": "DEV", "role": "TASK_OWNER",
        "read_set": ["app"],
    }
    one = DelegatedTaskLease.from_mapping({
        **base, "task_id": "one", "delegation_id": "delegation:m:one",
        "write_set": ["app/services"],
    })
    two = DelegatedTaskLease.from_mapping({
        **base, "task_id": "two", "delegation_id": "delegation:m:two",
        "write_set": ["app/services/x.py"],
    })
    assert write_conflicts((one, two)) == (("one", "two", "app/services"),)
    assert detect_candidate_conflicts(
        {"one": ["app/services"], "two": ["app/services/x.py"]}
    ) == ("one<->two:app/services",)


def test_agent_office_persists_leases_parallelizes_and_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "agent-office.db"))
    initialize_schema()
    root, sha = _repo(tmp_path)
    _, spec = _authorized_spec(root, sha)
    lock = threading.Lock()
    calls: dict[str, int] = {}

    def runner(task, workspace, timeout_seconds, lease):
        assert lease.role == "SPECIALIST_TASK_OWNER"
        with lock:
            calls[task.task_id] = calls.get(task.task_id, 0) + 1
            attempt = calls[task.task_id]
        if task.task_id == "retry" and attempt == 1:
            raise RuntimeError("recoverable transient")
        time.sleep(0.05)
        return {
            "status": "SUCCEEDED",
            "summary": task.task_id,
            "commands": ["git status --short"],
            "artifacts": [],
            "tests": [],
            "usage": {"cost": 0},
        }

    service = AgentOfficeService(
        root,
        adapter=MunderAdapter(worker_runners={"specialist": runner}),
    )
    result = service.execute(
        spec,
        [_task("parallel-a"), _task("parallel-b"), _task("retry")],
    )
    assert result.status == "SUCCEEDED"
    assert result.evidence["HARNESS_SOLE_AUTHORITY"] == "PASS"
    assert result.evidence["HARNESS_MICROMANAGEMENT"] == "NO"
    assert result.evidence["PARALLEL_TASK_COUNT"] == 3
    assert result.evidence["PARALLELISM_SAVED_MS"] > 0
    retry = next(item for item in result.per_agent_results if item["task_id"] == "retry")
    assert retry["retry_count"] == 1
    persisted = get_lease("delegation:delegated-canary-mission:parallel-a")
    assert persisted is not None and persisted["status"] == "COMPLETED"
    events = list_task_events(mission_id="delegated-canary-mission")
    event_types = {item["event_type"] for item in events}
    assert {"TASK_CREATED", "TASK_STARTED", "TASK_ARTIFACT_CREATED", "TASK_COMPLETED"} <= event_types


def test_deterministic_codex_host_policy_failure_does_not_consume_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "agent-office.db"))
    initialize_schema()
    root, sha = _repo(tmp_path)
    _, spec = _authorized_spec(root, sha)
    calls = 0

    def runner(task, workspace, timeout_seconds, lease):
        nonlocal calls
        calls += 1
        return {
            "status": "BLOCKED",
            "error": "Codex Linux sandbox host policy failure",
            "exit_code": 1,
            "failure_stage": "bounded_development_exec",
            "stderr_class": "SANDBOX_HOST_POLICY_FAILURE",
            "sandbox_backend": "bubblewrap",
            "retryability": "DETERMINISTIC_NO_RETRY",
            "recoverable": False,
        }

    task = _task("sandbox-host-policy")
    task = type(task).from_mapping(
        {
            **task.to_dict(),
            "agent": "codex-development",
            "retry_budget": 1,
        }
    )
    result = AgentOfficeService(
        root,
        adapter=MunderAdapter(worker_runners={"codex-development": runner}),
    ).execute(spec, [task])
    assert result.status == "FAILED"
    assert calls == 1
    item = result.per_agent_results[0]
    assert item["status"] == "BLOCKED"
    assert item["attempt_count"] == 1
    assert item["retry_count"] == 0
    assert item["retryability"] == "DETERMINISTIC_NO_RETRY"


def test_agent_office_serializes_overlapping_write_sets(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "agent-office.db"))
    initialize_schema()
    root, sha = _repo(tmp_path)
    _, spec = _authorized_spec(root, sha, max_parallelism=3)

    def runner(task, workspace, timeout_seconds, lease):
        time.sleep(0.02)
        return {"status": "SUCCEEDED", "summary": task.task_id, "commands": ["git status"]}

    result = AgentOfficeService(
        root,
        adapter=MunderAdapter(worker_runners={"specialist": runner}),
    ).execute(
        spec,
        [
            _task("one", ["a.txt"]),
            _task("two", ["a.txt"]),
            _task("three", ["b.txt"]),
        ],
    )
    assert result.status == "SUCCEEDED"
    assert result.evidence["CONFLICTS_DETECTED"]
    assert result.evidence["SERIAL_TASK_COUNT"] >= 1


def test_integration_gate_never_promotes_canonical_branch(tmp_path):
    root, sha = _repo(tmp_path)
    (root / "a.txt").write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "candidate"], cwd=root, check=True, capture_output=True)
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    result = run_integration_gate(
        repository_root=root,
        base_sha=sha,
        candidate_commit_sha=candidate,
        allowed_paths=["a.txt"],
        focused_test_commands=[["python", "-c", "assert 2 + 2 == 4"]],
        contract_test_commands=[["git", "diff", "--check", sha, candidate]],
        quality_checks={"QUALITY_REGRESSION": "NO"},
        performance_checks={"PERFORMANCE_REGRESSION": "NO"},
    )
    assert result.status == "PASS"
    assert result.integration_candidate is True
    assert result.canonical_push_authority == "NONE"


def test_task_owner_registry_covers_all_executable_agent_capabilities():
    from app.services.agent_office.task_owner_registry import audit_task_owner_profiles

    audit = audit_task_owner_profiles()
    assert audit["status"] == "PASS", audit
    assert audit["profile_count"] == audit["expected_agent_capability_count"]
    assert audit["missing"] == []
    assert audit["invalid"] == []


def test_mission_event_stream_reaches_reduction_without_polling_state(tmp_path, monkeypatch):
    from app.database.agent_office_mission_repository import (
        claim_mission,
        complete_mission,
        create_mission,
        list_mission_events,
        mark_ready_for_reduction,
    )

    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "missions.db"))
    initialize_schema()
    create_mission(
        mission_id="event-mission",
        goal_id="event-goal",
        harness_decision_id="event-decision",
        authorization_id="event-authorization",
        execution_id="event-execution",
        base_sha="a" * 40,
        request_payload={"spec": {}, "tasks": []},
    )
    claim_mission("event-mission", worker_id="worker:1")
    mark_ready_for_reduction(
        "event-mission",
        result_payload={"status": "SUCCEEDED"},
    )
    complete_mission(
        "event-mission",
        reduction_payload={"status": "READY_FOR_HARNESS_DECISION"},
    )
    assert [item["event_type"] for item in list_mission_events(mission_id="event-mission")] == [
        "MISSION_DELEGATED",
        "MISSION_EXECUTION_STARTED",
        "MISSION_READY_FOR_REDUCTION",
        "MISSION_REDUCED",
    ]
