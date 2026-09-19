from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
from typing import Any, Mapping

from app.services.agent_office.contracts import AgentOfficeTask
from app.services.agent_office.delegation import DelegatedTaskLease

CODEX_BOUNDED_DEVELOPMENT_CAPABILITY = "agent-office.codex.bounded-development"

_FORBIDDEN_COMMANDS = {
    "curl", "wget", "ssh", "scp", "rsync", "gh", "docker", "podman",
}


_SENSITIVE_ENV = re.compile(r"(?:token|secret|password|credential|api[_-]?key|github)", re.I)
_SAFE_ENV_KEYS = {
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
    "TMPDIR", "TEMP", "TMP", "TERM", "SHELL", "XDG_CONFIG_HOME",
    "XDG_DATA_HOME", "XDG_CACHE_HOME", "CODEX_HOME",
}
_WIF_RUNTIME_KEYS = {
    "OPENAI_FEDERATION_RULE_ID",
    "OPENAI_IDENTITY_TOKEN_FILE",
}
CODEX_SHELL_ENVIRONMENT_POLICY_ARGS = (
    "--config",
    "shell_environment_policy.ignore_default_excludes=false",
    "--config",
    'shell_environment_policy.include_only=["PATH","USER","LOGNAME","LANG","LC_ALL","LC_CTYPE","TERM","TMPDIR","TEMP","TMP","PYTHONPATH","SHELL"]',
)


def codex_sanitized_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    source = os.environ if source is None else source
    for key, value in source.items():
        if key in _WIF_RUNTIME_KEYS:
            result[key] = value
            continue
        if key not in _SAFE_ENV_KEYS:
            continue
        if _SENSITIVE_ENV.search(key):
            continue
        result[key] = value
    return result


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    sanitized_env: bool = False,
) -> subprocess.CompletedProcess[str]:
    if timeout <= 0:
        raise subprocess.TimeoutExpired(command, timeout)
    return subprocess.run(
        command,
        cwd=cwd,
        timeout=timeout,
        check=False,
        capture_output=True,
        text=True,
        env=codex_sanitized_environment() if sanitized_env else None,
    )


def _changed_paths(workspace: Path, base_sha: str) -> tuple[str, ...]:
    tracked = _run(
        ["git", "diff", "--name-only", base_sha, "--"],
        cwd=workspace,
        timeout=30,
    ).stdout.splitlines()
    untracked = _run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=workspace,
        timeout=30,
    ).stdout.splitlines()
    return tuple(sorted(set(filter(None, (*tracked, *untracked)))))


def _commands(stdout: str) -> tuple[str, ...]:
    commands: list[str] = []
    for line in str(stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") not in {"command_execution", "command"}:
            continue
        command = item.get("command") or item.get("command_line") or item.get("text")
        if isinstance(command, str) and command.strip():
            commands.append(command.strip())
    return tuple(commands)


def _final_text(stdout: str) -> str:
    result = ""
    for line in str(stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                result = text
    return result[:12_000]


def _validate_command(command: str, allowed_tools: tuple[str, ...]) -> None:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise PermissionError("Codex emitted an unparsable command") from exc
    if not parts:
        return
    tool = Path(parts[0]).name
    normalized = " ".join(parts)
    if tool in _FORBIDDEN_COMMANDS:
        raise PermissionError(f"Codex attempted forbidden command: {tool}")
    if re.search(r"(?<![A-Za-z0-9_-])(?:curl|wget|ssh|scp|rsync|gh|docker|podman)(?![A-Za-z0-9_-])", normalized):
        raise PermissionError("Codex attempted forbidden external/network command")
    if re.search(r"(?<![A-Za-z0-9_-])git\s+(?:push|pull|fetch|merge|rebase|remote)(?![A-Za-z0-9_-])", normalized):
        raise PermissionError("Codex attempted forbidden git side effect")
    if tool not in allowed_tools:
        raise PermissionError(f"Codex command is outside COMMAND_ALLOWLIST: {tool}")


def _candidate_commit(
    *,
    workspace: Path,
    changed: tuple[str, ...],
    task_id: str,
) -> str:
    _run(["git", "config", "user.name", "BR Agent Office Candidate"], cwd=workspace, timeout=15)
    _run(["git", "config", "user.email", "agent-office@br-no-gta.invalid"], cwd=workspace, timeout=15)
    add = _run(["git", "add", "--", *changed], cwd=workspace, timeout=30)
    if add.returncode != 0:
        raise RuntimeError("candidate git add failed")
    commit = _run(
        ["git", "commit", "-m", f"candidate({task_id}): bounded development result"],
        cwd=workspace,
        timeout=60,
    )
    if commit.returncode != 0:
        raise RuntimeError("candidate local commit failed")
    sha = _run(["git", "rev-parse", "HEAD"], cwd=workspace, timeout=15)
    if sha.returncode != 0:
        raise RuntimeError("candidate commit identity unavailable")
    return sha.stdout.strip()


def codex_bounded_development_worker(
    task: AgentOfficeTask,
    workspace: Path,
    timeout_seconds: float,
    lease: DelegatedTaskLease | None = None,
) -> dict[str, Any]:
    if lease is None:
        raise PermissionError("bounded development requires a DelegatedTaskLease")
    lease.assert_active()
    if task.capability != CODEX_BOUNDED_DEVELOPMENT_CAPABILITY:
        raise PermissionError("bounded Codex received a different capability")
    if lease.capability_ids != (CODEX_BOUNDED_DEVELOPMENT_CAPABILITY,):
        raise PermissionError("lease capability mismatch")
    if not lease.write_set:
        raise PermissionError("bounded Codex requires an explicit write_set")
    if "edit" not in lease.allowed_actions or "commit_candidate" not in lease.allowed_actions:
        raise PermissionError("bounded Codex lease does not authorize candidate development")

    deadline = time.monotonic() + min(timeout_seconds, lease.time_budget_seconds)

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise subprocess.TimeoutExpired(["codex"], timeout_seconds)
        return value

    head = _run(["git", "rev-parse", "HEAD"], cwd=workspace, timeout=remaining())
    if head.returncode != 0 or head.stdout.strip() != lease.base_sha:
        raise PermissionError("bounded Codex worktree base SHA mismatch")

    auth = _run(
        ["codex", "login", "status"],
        cwd=workspace,
        timeout=remaining(),
        sanitized_env=True,
    )
    if auth.returncode != 0:
        raise RuntimeError("Codex authentication prerequisite is unavailable")

    prompt = (
        "You are the bounded-development task owner under one existing DeepSeek Harness "
        "delegation lease. The Harness has already decided scope and authority. Work autonomously "
        "inside this disposable git worktree until the task is complete or escalation is required. "
        "Do not push, merge, fetch, access secrets, use network tools, change authority/policy, "
        "publish, deploy, or touch paths outside WRITE_SET. Do not create additional authority. "
        "You may inspect, edit, test and locally iterate within the lease. Do NOT commit; the "
        "deterministic Agent Office integration boundary will create the candidate commit.\n\n"
        f"TASK_ID={lease.task_id}\n"
        f"DELEGATION_ID={lease.delegation_id}\n"
        f"BASE_SHA={lease.base_sha}\n"
        f"WRITE_SET={json.dumps(lease.write_set)}\n"
        f"READ_SET={json.dumps(lease.read_set)}\n"
        f"ALLOWED_TOOLS={json.dumps(lease.allowed_tools)}\n"
        f"ACCEPTANCE_CRITERIA={json.dumps(lease.acceptance_criteria)}\n"
        f"EXPECTED_OUTPUTS={json.dumps(lease.expected_outputs)}\n"
        f"OBJECTIVE={task.objective}\n"
        "Return a concise engineering summary only after local validation."
    )
    command = [
        "codex",
        *CODEX_SHELL_ENVIRONMENT_POLICY_ARGS,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--color", "never",
        "--json",
        "--sandbox", "workspace-write",
        "-C", str(workspace),
        prompt,
    ]
    completed = _run(
        command,
        cwd=workspace,
        timeout=remaining(),
        sanitized_env=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("Codex bounded-development execution failed")

    observed_commands = _commands(completed.stdout)
    if len(observed_commands) > lease.tool_call_budget:
        raise RuntimeError("Codex exceeded tool_call_budget")
    for observed in observed_commands:
        _validate_command(observed, lease.allowed_tools)

    changed = _changed_paths(workspace, lease.base_sha)
    if not changed:
        raise RuntimeError("Codex bounded-development produced no candidate patch")
    outside = tuple(path for path in changed if not lease.allows_path(path, write=True))
    if outside:
        raise PermissionError(f"Codex changed paths outside lease: {outside}")

    diff_stat = _run(
        ["git", "diff", "--stat", lease.base_sha, "--"],
        cwd=workspace,
        timeout=remaining(),
    ).stdout.strip()
    candidate_sha = _candidate_commit(
        workspace=workspace,
        changed=changed,
        task_id=task.task_id,
    )
    tests = [
        {
            "name": "candidate-working-tree-path-boundary",
            "status": "PASS",
            "files": list(changed),
        }
    ]
    return {
        "status": "SUCCEEDED",
        "summary": _final_text(completed.stdout) or "Codex bounded candidate created",
        "commands": list(observed_commands),
        "artifacts": [f"candidate-commit:{candidate_sha}"],
        "tests": tests,
        "usage": {
            "cost": 0.0,
            "tool_calls": len(observed_commands),
            "retry_count": 0,
        },
        "candidate": {
            "STATUS": "READY_FOR_INTEGRATION",
            "BASE_SHA": lease.base_sha,
            "RESULT_COMMIT_SHA": candidate_sha,
            "FILES_CHANGED": list(changed),
            "DIFF_STAT": diff_stat,
            "COMMANDS_EXECUTED": list(observed_commands),
            "TESTS_RUN": [item["name"] for item in tests],
            "TEST_RESULTS": tests,
            "BENCHMARK_RESULTS": [],
            "ARTIFACT_REFS": [f"candidate-commit:{candidate_sha}"],
            "EVIDENCE_REFS": [f"delegation:{lease.delegation_id}"],
            "WARNINGS": [],
            "ESCALATIONS": [],
            "CANDIDATE_READY_FOR_INTEGRATION": True,
        },
        "canonical_push_authority": "NONE",
        "worktree_isolation": "PASS",
    }
