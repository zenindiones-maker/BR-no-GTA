from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from app.services.agent_office.contracts import (
    AgentOfficeExecutionSpec,
    AgentOfficeTask,
)
from app.services.agent_office.evidence import evidence_digest, sanitize_evidence
from app.services.agent_office import munder_adapter
from app.services.agent_office.munder_adapter import CODEX_READONLY_CAPABILITY, MunderAdapter
from app.services.agent_office.service import AgentOfficeService
from app.services.agent_office_harness_service import (
    execute_authorized_agent_office,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


CAPABILITY_ID = "agent-office.execute"


def _repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent-office@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Agent Office Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/zenindiones-maker/BR-no-GTA.git"],
        cwd=root,
        check=True,
    )
    (root / "README.md").write_text("bounded\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "test base"], cwd=root, check=True, capture_output=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return root, sha


def _authorization(*, execution_id: str = "office-execution-1"):
    return issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{CAPABILITY_ID}",
        harness_decision_id="office-decision-1",
        execution_id=execution_id,
        lineage={"goal_id": "goal-office-1"},
    )


def _spec(root: Path, sha: str, authorization=None, **overrides):
    authorization = authorization or _authorization()
    values = {
        "execution_id": authorization.execution_id,
        "goal_id": "goal-office-1",
        "brain_decision_id": authorization.harness_decision_id,
        "harness_authorization_id": authorization.authorization_id,
        "authorized_action": "DEVELOPMENT",
        "task_type": "READ_ONLY_CODE_ANALYSIS",
        "repository": "zenindiones-maker/BR-no-GTA",
        "branch": "main",
        "base_sha": sha,
        "allowed_agents": ["deterministic-analysis", "codex"],
        "allowed_capabilities": ["repository.read", "addy:code-review-and-quality"],
        "allowed_paths": ["README.md"],
        "forbidden_actions": [
            "youtube_publish",
            "autonomous_schedule",
            "secret_access",
            "policy_mutation",
        ],
        "max_parallelism": 2,
        "time_budget_seconds": 30,
        "cost_budget": 0,
        "expected_outputs": ["analysis"],
        "evidence_requirements": ["commands", "per_agent_results", "knowledge_return_path"],
    }
    values.update(overrides)
    return AgentOfficeExecutionSpec.from_mapping(values)


def _task(task_id="task-1", agent="deterministic-analysis", **overrides):
    values = {
        "task_id": task_id,
        "agent": agent,
        "capability": "repository.read",
        "action": "analyze",
        "objective": "Inspect tracked files without mutation.",
    }
    values.update(overrides)
    return AgentOfficeTask.from_mapping(values)


def test_execution_spec_validates_required_fields_and_bounds(tmp_path):
    root, sha = _repo(tmp_path)
    spec = _spec(root, sha)
    assert spec.max_parallelism == 2
    assert spec.coordinator_role == "AGENT_OFFICE_COORDINATOR"
    assert spec.authority == "DELEGATED_ONLY"

    with pytest.raises(ValueError, match="max_parallelism"):
        _spec(root, sha, max_parallelism=0)
    with pytest.raises(ValueError, match="base_sha"):
        _spec(root, "not-a-sha")


def test_missing_or_fabricated_authorization_is_rejected(tmp_path):
    root, sha = _repo(tmp_path)
    spec = _spec(root, sha, harness_authorization_id="missing")
    with pytest.raises(PermissionError, match="not found"):
        AgentOfficeService(root).execute(spec, [_task()])


def test_authorization_lineage_and_action_are_enforced(tmp_path):
    root, sha = _repo(tmp_path)
    authorization = _authorization(execution_id="different")
    spec = _spec(root, sha, authorization=authorization, execution_id="forged")
    with pytest.raises(PermissionError, match="execution_id mismatch"):
        AgentOfficeService(root).execute(spec, [_task()])

    with pytest.raises(ValueError, match="authorized_action"):
        _spec(root, sha, authorized_action="YOUTUBE")


def test_branch_and_base_sha_must_match_contract(tmp_path):
    root, sha = _repo(tmp_path)
    with pytest.raises(PermissionError, match="repository mismatch"):
        AgentOfficeService(root).execute(
            _spec(root, sha, repository="other/project"), [_task()]
        )
    with pytest.raises(PermissionError, match="branch mismatch"):
        AgentOfficeService(root).execute(_spec(root, sha, branch="other"), [_task()])
    with pytest.raises(PermissionError, match="base SHA mismatch"):
        AgentOfficeService(root).execute(_spec(root, "a" * 40), [_task()])


@pytest.mark.parametrize(
    ("field", "task_override", "message"),
    [
        ("allowed_agents", {"agent": "unknown"}, "agent is not allowed"),
        ("allowed_capabilities", {"capability": "shell.exec"}, "capability is not allowed"),
        ("forbidden_actions", {"action": "youtube_publish"}, "action is forbidden"),
    ],
)
def test_agent_capability_and_forbidden_action_enforcement(tmp_path, field, task_override, message):
    root, sha = _repo(tmp_path)
    with pytest.raises(PermissionError, match=message):
        AgentOfficeService(root).execute(_spec(root, sha), [_task(**task_override)])


def test_each_worker_uses_a_distinct_worktree(tmp_path):
    root, sha = _repo(tmp_path)
    workspaces = []

    def runner(task, workspace, timeout_seconds):
        workspaces.append(workspace)
        assert timeout_seconds > 0
        return {"status": "SUCCEEDED", "summary": task.task_id, "commands": ["git ls-files"]}

    service = AgentOfficeService(root, adapter=MunderAdapter(worker_runner=runner))
    result = service.execute(_spec(root, sha), [_task("a"), _task("b")])
    assert result.status == "SUCCEEDED"
    assert len(set(workspaces)) == 2
    assert all(path != root for path in workspaces)
    assert result.evidence["worktree_isolation"] == "PASS"


def test_mutation_outside_allowed_paths_fails_closed(tmp_path):
    root, sha = _repo(tmp_path)

    def runner(task, workspace, timeout_seconds):
        (workspace / "forbidden.txt").write_text("no", encoding="utf-8")
        return {"status": "SUCCEEDED", "summary": "attempted mutation"}

    result = AgentOfficeService(root, adapter=MunderAdapter(worker_runner=runner)).execute(
        _spec(root, sha), [_task()]
    )
    assert result.status == "FAILED"
    assert result.files_changed == ("forbidden.txt",)
    assert "outside allowed_paths" in result.errors[0]


def test_worker_failure_and_partial_failure_are_aggregated(tmp_path):
    root, sha = _repo(tmp_path)

    def runner(task, workspace, timeout_seconds):
        if task.task_id == "bad":
            raise RuntimeError("private executor detail")
        return {"status": "SUCCEEDED", "summary": "ok"}

    service = AgentOfficeService(root, adapter=MunderAdapter(worker_runner=runner))
    partial = service.execute(_spec(root, sha), [_task("good"), _task("bad")])
    assert partial.status == "PARTIAL"
    assert len(partial.per_agent_results) == 2
    assert "private executor detail" not in json.dumps(partial.to_dict())

    failed = service.execute(_spec(root, sha), [_task("bad")])
    assert failed.status == "FAILED"


def test_codex_requires_a_trusted_registered_runner(tmp_path):
    root, sha = _repo(tmp_path)
    blocked = AgentOfficeService(
        root, adapter=MunderAdapter(worker_runners={})
    ).execute(_spec(root, sha), [_task(agent="codex")])
    assert blocked.status == "FAILED"
    assert "not registered by the Harness" in blocked.errors[0]

    calls = []

    def registered_codex(task, workspace, timeout_seconds):
        calls.append(task.capability)
        return {"status": "SUCCEEDED", "summary": "bounded Codex result"}

    adapter = MunderAdapter(worker_runners={"codex": registered_codex})
    result = AgentOfficeService(root, adapter=adapter).execute(
        _spec(root, sha), [_task(agent="codex", capability="addy:code-review-and-quality")]
    )
    assert result.status == "SUCCEEDED"
    assert calls == ["addy:code-review-and-quality"]


def test_default_codex_worker_refuses_canonical_addy_bypass(tmp_path):
    root, sha = _repo(tmp_path)
    result = AgentOfficeService(root).execute(
        _spec(root, sha),
        [_task(agent="codex", capability="addy:code-review-and-quality")],
    )
    assert result.status == "FAILED"
    assert (
        "Canonical Addy capabilities must execute through the Harness Addy boundary"
        in result.errors
    )


def test_default_codex_worker_executes_only_internal_readonly_capability(tmp_path, monkeypatch):
    root, sha = _repo(tmp_path)
    calls = []

    def fake_process(command, *, cwd, timeout_seconds):
        calls.append((list(command), cwd, timeout_seconds))
        if command == ["codex", "login", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "bounded review complete"},
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(munder_adapter, "_codex_process", fake_process)
    result = AgentOfficeService(root).execute(
        _spec(
            root,
            sha,
            allowed_capabilities=["repository.read", CODEX_READONLY_CAPABILITY],
        ),
        [_task(agent="codex", capability=CODEX_READONLY_CAPABILITY)],
    )
    assert result.status == "SUCCEEDED"
    assert calls[0][0] == ["codex", "login", "status"]
    assert calls[1][0][:2] == ["codex", "exec"]
    assert "--sandbox" in calls[1][0]
    assert calls[1][0][calls[1][0].index("--sandbox") + 1] == "read-only"
    assert result.per_agent_results[0]["engine_result"]["canonical_addy_bypass"] is False


def test_codex_subprocess_receives_enforced_time_budget(tmp_path, monkeypatch):
    root, sha = _repo(tmp_path)
    observed = []

    def bounded_process(command, *, cwd, timeout_seconds):
        observed.append(timeout_seconds)
        if command == ["codex", "login", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    monkeypatch.setattr(munder_adapter, "_codex_process", bounded_process)
    result = AgentOfficeService(root).execute(
        _spec(
            root,
            sha,
            time_budget_seconds=1,
            allowed_capabilities=["repository.read", CODEX_READONLY_CAPABILITY],
        ),
        [_task(agent="codex", capability=CODEX_READONLY_CAPABILITY)],
    )
    assert result.status == "FAILED"
    assert "worker execution failed" in result.errors
    assert observed
    assert all(0 < value <= 1 for value in observed)


def test_timeout_and_cost_budget_fail_closed(tmp_path):
    root, sha = _repo(tmp_path)
    ticks = iter([0.0, 2.0, 2.0, 2.0])

    def runner(task, workspace, timeout_seconds):
        return {"status": "SUCCEEDED", "summary": "late", "usage": {"cost": 2.0}}

    adapter = MunderAdapter(worker_runner=runner, clock=lambda: next(ticks))
    result = AgentOfficeService(root, adapter=adapter).execute(
        _spec(root, sha, time_budget_seconds=1, cost_budget=1), [_task()]
    )
    assert result.status == "FAILED"
    assert any("time budget" in error for error in result.errors)
    assert any("cost budget" in error for error in result.errors)


def test_evidence_is_deterministic_and_redacts_secrets():
    one = {"tasks": [{"task_id": "b"}, {"task_id": "a"}], "status": "SUCCEEDED"}
    two = {"status": "SUCCEEDED", "tasks": [{"task_id": "b"}, {"task_id": "a"}]}
    assert evidence_digest(one) == evidence_digest(two)

    sanitized = sanitize_evidence(
        {"token": "secret-value", "nested": {"api_key": "abc", "safe": "ok"}}
    )
    assert sanitized == {"token": "[REDACTED]", "nested": {"api_key": "[REDACTED]", "safe": "ok"}}


def test_result_returns_only_evidence_to_harness_and_knowledge_boundary(tmp_path):
    root, sha = _repo(tmp_path)
    result = AgentOfficeService(root).execute(_spec(root, sha), [_task()])
    payload = result.to_dict()
    assert payload["coordinator_role"] == "AGENT_OFFICE_COORDINATOR"
    assert payload["authority"] == "DELEGATED_ONLY"
    assert payload["evidence"]["knowledge_return_path"] == (
        "Agent Office -> Evidence -> DeepSeek Harness -> Knowledge Brain"
    )
    assert payload["evidence"]["no_parallel_authority"] == "PASS"
    assert payload["evidence"]["no_autonomous_publishing"] == "PASS"
    assert payload["evidence"]["no_unauthorized_scheduler"] == "PASS"


def test_registry_and_harness_boundary_execute_agent_office(tmp_path):
    root, sha = _repo(tmp_path)
    record = GLOBAL_CAPABILITY_REGISTRY.get(CAPABILITY_ID)
    assert record is not None
    assert record.allowed_actions == ("DEVELOPMENT",)
    assert record.executor_binding.endswith("execute_agent_office_capability")
    requirements = " ".join(record.requirements).lower()
    assert "codex" in requirements
    assert "agent skills" in requirements

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute bounded agent office code analysis",
            authorized_action="DEVELOPMENT",
            required_capability_id=CAPABILITY_ID,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{CAPABILITY_ID}",
        harness_decision_id="office-decision-1",
        execution_id="office-execution-1",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": "goal-office-1",
        },
    )
    evidence = execute_authorized_agent_office(
        authorization=authorization,
        routing_decision=routing,
        payload={
            "goal_id": "goal-office-1",
            "task_type": "READ_ONLY_CODE_ANALYSIS",
            "repository": "zenindiones-maker/BR-no-GTA",
            "branch": "main",
            "base_sha": sha,
            "allowed_agents": ["deterministic-analysis"],
            "allowed_capabilities": ["repository.read"],
            "allowed_paths": ["README.md"],
            "max_parallelism": 1,
            "time_budget_seconds": 30,
            "cost_budget": 0,
            "expected_outputs": ["analysis"],
            "evidence_requirements": ["commands"],
            "tasks": [_task().to_dict()],
        },
        repository_root=root,
    )
    assert evidence.status == "EXECUTED"
    assert evidence.authority == "deepseek_harness"
    assert evidence.result["status"] == "SUCCEEDED"


def test_agent_office_never_accepts_autonomous_triggers_or_publish(tmp_path):
    root, sha = _repo(tmp_path)
    spec = _spec(root, sha)
    assert {"youtube_publish", "autonomous_schedule", "secret_access", "policy_mutation"}.issubset(
        set(spec.forbidden_actions)
    )
    policy = json.loads(
        (Path(__file__).parents[1] / "integrations/munder_difflin/config/policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy["autonomous_scheduling"] is False
    assert policy["slack_trigger"] is False
    assert policy["webhook_trigger"] is False
    assert policy["auto_mode"] is False
    assert policy["auto_publish"] is False


def test_official_harness_mcp_path_returns_canonical_agent_office_evidence():
    from app.integrations.deepseek_harness import server

    root = Path(__file__).parents[1]
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() or os.getenv("GITHUB_HEAD_REF") or os.getenv("GITHUB_REF_NAME")
    assert branch
    response = json.loads(
        server.br_capability_execute(
            capability_id=CAPABILITY_ID,
            authorized_action="DEVELOPMENT",
            payload_json=json.dumps(
                {
                    "goal_id": "mcp-office-goal",
                    "task_type": "READ_ONLY_CODE_ANALYSIS",
                    "repository": "zenindiones-maker/BR-no-GTA",
                    "branch": branch,
                    "base_sha": sha,
                    "allowed_agents": ["deterministic-analysis"],
                    "allowed_capabilities": ["repository.read"],
                    "allowed_paths": [],
                    "max_parallelism": 1,
                    "time_budget_seconds": 30,
                    "cost_budget": 0,
                    "expected_outputs": ["analysis"],
                    "evidence_requirements": ["commands"],
                    "tasks": [_task("mcp-read").to_dict()],
                }
            ),
        )
    )
    result = response["result"]
    assert result["status"] == "EXECUTED"
    assert result["authority"] == "deepseek_harness"
    assert result["result"]["status"] == "SUCCEEDED"
    assert response["evidence"]["capability_id"] == CAPABILITY_ID
