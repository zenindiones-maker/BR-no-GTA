from __future__ import annotations

import json
from dataclasses import replace
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
from app.services.agent_office.codex_bounded_worker import (
    CODEX_TUXEVIL_AUTH_MODE,
    _validate_command,
    codex_execution_failure,
    codex_tuxevil_provider_args,
)
from app.services.agent_office.munder_adapter import CODEX_READONLY_CAPABILITY, MunderAdapter
from app.services.agent_office.service import AgentOfficeService
from app.services.agent_office_harness_service import (
    build_agent_office_specialist_contract,
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
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "git status --short",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": "bounded review complete",
                        },
                    }
                ),
            ]
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
    assert calls[1][0][0] == "codex"
    assert "exec" in calls[1][0]
    assert "shell_environment_policy.ignore_default_excludes=false" in calls[1][0]
    assert any("shell_environment_policy.include_only" in item for item in calls[1][0])
    assert "--sandbox" in calls[1][0]
    assert calls[1][0][calls[1][0].index("--sandbox") + 1] == "read-only"
    assert result.per_agent_results[0]["engine_result"]["canonical_addy_bypass"] is False


def test_codex_sandbox_host_policy_failure_is_classified_without_secret_text():
    completed = subprocess.CompletedProcess(
        ["codex"],
        1,
        stdout="",
        stderr="bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted",
    )
    failure = codex_execution_failure(
        completed,
        failure_stage="bounded_development_exec",
    )
    assert failure == {
        "status": "BLOCKED",
        "error": "Codex Linux sandbox host policy failure",
        "exit_code": 1,
        "failure_stage": "bounded_development_exec",
        "stderr_class": "SANDBOX_HOST_POLICY_FAILURE",
        "sandbox_backend": "bubblewrap",
        "retryability": "DETERMINISTIC_NO_RETRY",
        "recoverable": False,
    }


def test_codex_readonly_sandbox_block_is_never_success(tmp_path, monkeypatch):
    root, sha = _repo(tmp_path)

    def blocked_process(command, *, cwd, timeout_seconds):
        if command == ["codex", "login", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": (
                        "Inspection blocked: bwrap: loopback: Failed RTM_NEWADDR: "
                        "Operation not permitted. No implementation files were read."
                    ),
                },
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(munder_adapter, "_codex_process", blocked_process)
    result = AgentOfficeService(root).execute(
        _spec(
            root,
            sha,
            allowed_capabilities=["repository.read", CODEX_READONLY_CAPABILITY],
        ),
        [_task(agent="codex", capability=CODEX_READONLY_CAPABILITY)],
    )
    assert result.status == "FAILED"
    item = result.per_agent_results[0]
    assert item["status"] == "BLOCKED"
    assert item["stderr_class"] == "SANDBOX_HOST_POLICY_FAILURE"
    assert item["retryability"] == "DETERMINISTIC_NO_RETRY"
    assert item["attempt_count"] == 1
    assert item["retry_count"] == 0


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
    assert "worker execution timed out" in result.errors
    assert observed
    assert all(0 < value <= 1 for value in observed)


def test_worker_failure_reason_preserves_only_allowlisted_internal_diagnostics():
    safe = munder_adapter._safe_worker_exception_reason(
        RuntimeError("Codex bounded-development produced no candidate patch")
    )
    assert safe == "Codex bounded-development produced no candidate patch"

    hidden = munder_adapter._safe_worker_exception_reason(
        RuntimeError("provider raw response contained arbitrary text")
    )
    assert hidden == "worker execution failed"


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



def test_agent_office_separate_mission_scopes_are_fail_closed(tmp_path, capsys):
    root, sha = _repo(tmp_path)
    spec = _spec(
        root,
        sha,
        allowed_paths=["README.md"],
        mission_read_scope=["README.md"],
        mission_write_scope=[],
    )
    valid = _task(
        read_set=["README.md"],
        allowed_paths=[],
        write_set=[],
    )
    lease = AgentOfficeService._build_task_lease(spec, valid)
    assert lease.read_set == ("README.md",)
    assert lease.write_set == ()

    invalid_read = _task(
        task_id="invalid-read",
        read_set=["app/services/harness_collaboration_service.py"],
        allowed_paths=[],
        write_set=[],
    )
    with pytest.raises(PermissionError, match="REQUEST_SCOPE_EXPANSION"):
        AgentOfficeService._build_task_lease(spec, invalid_read)
    output = capsys.readouterr().out
    assert 'TASK_ID="invalid-read"' in output
    assert 'OUT_OF_SCOPE_READ_PATHS=["app/services/harness_collaboration_service.py"]' in output
    assert 'OUT_OF_SCOPE_WRITE_PATHS=[]' in output

    write_spec = _spec(
        root,
        sha,
        allowed_paths=["README.md"],
        mission_read_scope=["README.md"],
        mission_write_scope=["README.md"],
    )
    invalid_write = _task(
        task_id="invalid-write",
        read_set=["README.md"],
        allowed_paths=["README.md"],
        write_set=["app/services/agent_office/service.py"],
    )
    with pytest.raises(PermissionError, match="REQUEST_SCOPE_EXPANSION"):
        AgentOfficeService._build_task_lease(write_spec, invalid_write)
    output = capsys.readouterr().out
    assert 'TASK_ID="invalid-write"' in output
    assert 'OUT_OF_SCOPE_WRITE_PATHS=["app/services/agent_office/service.py"]' in output


def test_delegated_task_cannot_expand_mission_scope(tmp_path):
    root, sha = _repo(tmp_path)
    spec = _spec(
        root,
        sha,
        allowed_paths=["README.md"],
        mission_read_scope=["README.md"],
        mission_write_scope=["README.md"],
    )
    attempted_expansion = _task(
        task_id="hermes-scope-expansion",
        read_set=["README.md"],
        allowed_paths=["README.md", "app"],
        write_set=[],
    )
    with pytest.raises(PermissionError, match="REQUEST_SCOPE_EXPANSION"):
        AgentOfficeService._build_task_lease(spec, attempted_expansion)


def test_registry_driven_specialist_contract_accepts_future_engineering_capability():
    current = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.bounded-development"
    )
    assert current is not None
    future = replace(
        current,
        capability_id="agent-office.future.safe-engineer",
        agent_id="future-safe-engineer",
        provider_id="future-local",
        version="7",
    )
    contract = build_agent_office_specialist_contract(
        record=future,
        payload={
            "task_id": "future-change",
            "task_class": "bounded-development",
            "objective": "Create a bounded candidate in app only",
            "allowed_paths": ["app"],
            "mission_read_scope": ["app", "tests"],
            "mission_write_scope": ["app"],
            "read_set": ["app", "tests"],
            "write_set": ["app"],
            "allowed_tools": ["git", "python", "pytest"],
            "acceptance_criteria": ["focused tests pass"],
        },
    )
    assert contract["agent_id"] == "future-safe-engineer"
    assert contract["mutation_capable"] is True
    assert contract["task"]["capability"] == "agent-office.future.safe-engineer"
    assert contract["task"]["agent"] == "future-safe-engineer"
    assert contract["task"]["write_set"] == ["app"]
    assert contract["task"]["allowed_actions"] == [
        "analyze", "inspect", "test", "benchmark", "edit", "commit_candidate"
    ]


def test_registry_driven_readonly_specialist_rejects_write_scope():
    readonly = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.readonly-analysis"
    )
    assert readonly is not None
    with pytest.raises(PermissionError, match="read-only"):
        build_agent_office_specialist_contract(
            record=readonly,
            payload={
                "task_id": "invalid-write",
                "task_class": "readonly-analysis",
                "objective": "Inspect architecture",
                "read_set": ["app"],
                "write_set": ["app"],
                "mission_read_scope": ["app"],
                "mission_write_scope": ["app"],
            },
        )


def test_registry_driven_specialist_rejects_tool_expansion():
    readonly = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.readonly-analysis"
    )
    assert readonly is not None
    with pytest.raises(PermissionError, match="tools expand"):
        build_agent_office_specialist_contract(
            record=readonly,
            payload={
                "task_id": "invalid-tool",
                "task_class": "readonly-analysis",
                "objective": "Inspect architecture",
                "read_set": ["app"],
                "mission_read_scope": ["app"],
                "allowed_tools": ["git", "curl"],
            },
        )


def test_codex_shell_wrapper_validates_inner_allowlisted_tools():
    allowed = ("git", "python", "pytest", "rg", "cat")
    _validate_command(
        "bash -lc 'git status --short && python -m pytest -q tests/test_agent_office.py'",
        allowed,
    )
    _validate_command(
        "sh -c 'rg candidate app | cat'",
        allowed,
    )


def test_bounded_codex_registry_allows_only_explicit_readonly_ls_extension():
    record = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.bounded-development"
    )
    assert record is not None
    assert "ls" in record.allowed_tools
    for forbidden in ("curl", "wget", "ssh", "scp", "rsync", "gh"):
        assert forbidden not in record.allowed_tools

    _validate_command("ls -la app/services/agent_office", record.allowed_tools)
    with pytest.raises(PermissionError, match="forbidden command"):
        _validate_command("curl https://example.invalid", record.allowed_tools)


@pytest.mark.parametrize(
    "command",
    (
        "bash -lc 'curl https://example.invalid'",
        "bash -lc 'git push origin HEAD'",
        "bash -lc 'sed -n 1,5p README.md'",
        "bash -lc 'python -c \"print(1)\" & python -c \"print(2)\"'",
        "bash -lc 'python -c \"print(1)\"; \\$(curl https://example.invalid)'",
    ),
)
def test_codex_shell_wrapper_cannot_expand_tool_or_side_effect_policy(command):
    with pytest.raises(PermissionError):
        _validate_command(
            command,
            ("git", "python", "pytest", "rg", "cat"),
        )


def test_tuxevil_codex_provider_mode_is_loopback_responses_only():
    args = codex_tuxevil_provider_args({
        "BR_CODEX_AUTH_MODE": CODEX_TUXEVIL_AUTH_MODE,
        "BR_CODEX_TUXEVIL_BASE_URL": "http://127.0.0.1:51200/v1",
        "BR_CODEX_TUXEVIL_MODEL": "gemini-3-flash",
        "BR_TUXEVIL_LOOPBACK_KEY": "loopback-bearer-secret-sentinel",
    })
    joined = " ".join(args)
    assert 'model_provider="br_tuxevil"' in joined
    assert 'model="gemini-3-flash"' in joined
    assert 'model_providers.br_tuxevil.base_url="http://127.0.0.1:51200/v1"' in joined
    assert 'model_providers.br_tuxevil.env_key="BR_TUXEVIL_LOOPBACK_KEY"' in joined
    assert 'model_providers.br_tuxevil.wire_api="responses"' in joined
    assert "model_providers.br_tuxevil.requires_openai_auth=false" in joined
    assert "OPENAI_API_KEY" not in joined
    assert "loopback-bearer-secret-sentinel" not in joined
    assert 'env_key="BR_TUXEVIL_LOOPBACK_KEY"' in joined
    assert "BR_TUXEVIL_LOOPBACK_KEY" in joined
    assert "tuxevil" not in args
    assert "Authorization: Bearer" not in joined
    assert "http://127.0.0.1:51200/v1" in joined
    assert "wire_api=\"responses\"" in joined
    assert "https://" not in joined


def test_tuxevil_codex_provider_rejects_non_loopback_endpoint():
    with pytest.raises(PermissionError, match="canonical loopback"):
        codex_tuxevil_provider_args({
            "BR_CODEX_AUTH_MODE": CODEX_TUXEVIL_AUTH_MODE,
            "BR_CODEX_TUXEVIL_BASE_URL": "https://example.invalid/v1",
            "BR_CODEX_TUXEVIL_MODEL": "gemini-3-flash",
            "BR_TUXEVIL_LOOPBACK_KEY": "tuxevil",
        })


def test_tuxevil_loopback_key_is_the_only_proxy_credential_passed_to_codex():
    from app.services.agent_office.codex_bounded_worker import (
        codex_sanitized_environment,
    )

    env=codex_sanitized_environment({
        "PATH": "/usr/bin",
        "BR_TUXEVIL_LOOPBACK_KEY": "loopback-only",
        "TUXEVIL_ACCOUNTS_JSON_B64": "forbidden-upstream-store",
        "OPENAI_API_KEY": "forbidden-platform-key",
        "ANTIGRAVITY_REFRESH_TOKEN": "forbidden-refresh-token",
    })
    assert env["BR_TUXEVIL_LOOPBACK_KEY"] == "loopback-only"
    assert "TUXEVIL_ACCOUNTS_JSON_B64" not in env
    assert "OPENAI_API_KEY" not in env
    assert "ANTIGRAVITY_REFRESH_TOKEN" not in env


def test_agent_office_codex_workers_keep_tuxevil_transport_inside_existing_workers():
    bounded = Path(
        "app/services/agent_office/codex_bounded_worker.py"
    ).read_text(encoding="utf-8")
    readonly = Path(
        "app/services/agent_office/munder_adapter.py"
    ).read_text(encoding="utf-8")
    assert "provider_args = codex_tuxevil_provider_args()" in bounded
    assert "provider_args = codex_tuxevil_provider_args()" in readonly
    assert '["codex", "login", "status"]' in bounded
    assert '["codex", "login", "status"]' in readonly
    assert "if not provider_args:" in bounded
    assert "if not provider_args:" in readonly


def test_codex_structured_metric_parser_requires_real_numeric_before_after():
    from app.services.agent_office.codex_bounded_worker import _structured_metric

    metric = _structured_metric(
        'Resumo\nBR_METRIC_JSON={"metric_name":"latency_ms","baseline":120.0,'
        '"candidate":90.0,"unit":"ms","direction":"LOWER_IS_BETTER",'
        '"measurement_command":"python benchmark.py"}'
    )
    assert metric is not None
    assert metric["baseline"] == 120.0
    assert metric["candidate"] == 90.0
    assert metric["improvement_delta"] == 30.0
    assert metric["improved"] is True
    assert metric["evidence_kind"] == "MEASURED_BEFORE_AFTER"
