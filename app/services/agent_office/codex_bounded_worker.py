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

CODEX_TUXEVIL_AUTH_MODE = "TUXEVIL_ANTIGRAVITY_RESPONSES_PROXY"
_CODEX_TUXEVIL_DEFAULT_BASE_URL = "http://127.0.0.1:51200/v1"
_CODEX_TUXEVIL_DEFAULT_MODEL = "gemini-3-flash"
_CODEX_TUXEVIL_LOOPBACK_KEY_ENV = "BR_TUXEVIL_LOOPBACK_KEY"
_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def codex_tuxevil_provider_args(
    source: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    source = os.environ if source is None else source
    mode = str(source.get("BR_CODEX_AUTH_MODE") or "").strip()
    if not mode:
        return ()
    if mode != CODEX_TUXEVIL_AUTH_MODE:
        raise PermissionError("unsupported BR_CODEX_AUTH_MODE")

    base_url = str(
        source.get("BR_CODEX_TUXEVIL_BASE_URL")
        or _CODEX_TUXEVIL_DEFAULT_BASE_URL
    ).strip().rstrip("/")
    if base_url != _CODEX_TUXEVIL_DEFAULT_BASE_URL:
        raise PermissionError(
            "Tuxevil Codex provider must remain on the canonical loopback endpoint"
        )

    model = str(
        source.get("BR_CODEX_TUXEVIL_MODEL")
        or _CODEX_TUXEVIL_DEFAULT_MODEL
    ).strip()
    if not _SAFE_MODEL_ID.fullmatch(model):
        raise PermissionError("invalid Tuxevil Codex model id")
    if not str(source.get(_CODEX_TUXEVIL_LOOPBACK_KEY_ENV) or "").strip():
        raise PermissionError("Tuxevil loopback client credential is unavailable")

    return (
        "--config",
        'model_provider="br_tuxevil"',
        "--config",
        f'model="{model}"',
        "--config",
        'model_providers.br_tuxevil.name="BR Tuxevil"',
        "--config",
        f'model_providers.br_tuxevil.base_url="{base_url}"',
        "--config",
        'model_providers.br_tuxevil.env_key="BR_TUXEVIL_LOOPBACK_KEY"',
        "--config",
        'model_providers.br_tuxevil.wire_api="responses"',
        "--config",
        "model_providers.br_tuxevil.requires_openai_auth=false",
        "--config",
        "model_providers.br_tuxevil.supports_websockets=false",
    )


def codex_uses_tuxevil_proxy(
    source: Mapping[str, str] | None = None,
) -> bool:
    return bool(codex_tuxevil_provider_args(source))


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
_TUXEVIL_RUNTIME_KEYS = {
    "BR_TUXEVIL_LOOPBACK_KEY",
}
CODEX_SHELL_ENVIRONMENT_POLICY_ARGS = (
    "--config",
    "shell_environment_policy.ignore_default_excludes=false",
    "--config",
    'shell_environment_policy.include_only=["PATH","USER","LOGNAME","LANG","LC_ALL","LC_CTYPE","TERM","TMPDIR","TEMP","TMP","PYTHONPATH","SHELL"]',
)

_SANDBOX_HOST_POLICY_PATTERNS = (
    "bwrap:",
    "failed rtm_newaddr",
    "apparmor_restrict_unprivileged_userns",
    "unprivileged user namespace",
    "/proc/self/uid_map",
)


def is_codex_sandbox_host_policy_failure(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(pattern in lowered for pattern in _SANDBOX_HOST_POLICY_PATTERNS)


def codex_execution_failure(
    completed: subprocess.CompletedProcess[str],
    *,
    failure_stage: str,
    sandbox_backend: str = "bubblewrap",
) -> dict[str, Any] | None:
    combined = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    if is_codex_sandbox_host_policy_failure(combined):
        return {
            "status": "BLOCKED",
            "error": "Codex Linux sandbox host policy failure",
            "exit_code": int(completed.returncode),
            "failure_stage": failure_stage,
            "stderr_class": "SANDBOX_HOST_POLICY_FAILURE",
            "sandbox_backend": sandbox_backend,
            "retryability": "DETERMINISTIC_NO_RETRY",
            "recoverable": False,
        }
    if completed.returncode != 0:
        return {
            "status": "FAILED",
            "error": "Codex process execution failed",
            "exit_code": int(completed.returncode),
            "failure_stage": failure_stage,
            "stderr_class": "CODEX_PROCESS_FAILURE",
            "sandbox_backend": sandbox_backend,
            "retryability": "TRANSIENT_RETRYABLE",
            "recoverable": True,
        }
    return None


def codex_sanitized_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    source = os.environ if source is None else source
    for key, value in source.items():
        if key in _WIF_RUNTIME_KEYS or key in _TUXEVIL_RUNTIME_KEYS:
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


def _measurement_required(task: AgentOfficeTask, lease: DelegatedTaskLease) -> bool:
    text = " ".join([
        task.objective,
        *lease.acceptance_criteria,
        *lease.expected_outputs,
    ]).casefold()
    return any(marker in text for marker in (
        "measur", "mensur", "benchmark", "latency", "latência",
        "performance", "desempenho", "before/after", "antes/depois",
        "baseline", "candidate metric", "improvement delta",
        "redund", "throughput",
    ))


def _structured_metric(final_text: str) -> dict[str, Any] | None:
    prefix = "BR_METRIC_JSON="
    for line in reversed(str(final_text or "").splitlines()):
        if not line.strip().startswith(prefix):
            continue
        raw = line.strip()[len(prefix):]
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Codex emitted invalid BR_METRIC_JSON") from exc
        required = ("metric_name", "baseline", "candidate", "unit", "direction")
        if not isinstance(value, dict) or any(key not in value for key in required):
            raise RuntimeError("BR_METRIC_JSON is missing required fields")
        baseline = value["baseline"]
        candidate = value["candidate"]
        if isinstance(baseline, bool) or not isinstance(baseline, (int, float)):
            raise RuntimeError("BR_METRIC_JSON baseline must be numeric")
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            raise RuntimeError("BR_METRIC_JSON candidate must be numeric")
        direction = str(value["direction"]).strip().upper()
        if direction not in {"LOWER_IS_BETTER", "HIGHER_IS_BETTER"}:
            raise RuntimeError("BR_METRIC_JSON direction is invalid")
        computed = (
            float(baseline) - float(candidate)
            if direction == "LOWER_IS_BETTER"
            else float(candidate) - float(baseline)
        )
        return {
            "metric_name": str(value["metric_name"]).strip(),
            "baseline": float(baseline),
            "candidate": float(candidate),
            "unit": str(value["unit"]).strip(),
            "direction": direction,
            "improvement_delta": computed,
            "improved": computed > 0,
            "measurement_command": str(
                value.get("measurement_command") or ""
            ).strip(),
            "evidence_kind": "MEASURED_BEFORE_AFTER",
        }
    return None


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

    provider_args = codex_tuxevil_provider_args()
    if not provider_args:
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
        "You may inspect, edit, test and locally iterate within the lease. This task has already "
        "been selected by the Harness as bounded-development: successful completion requires a "
        "non-empty candidate patch entirely inside WRITE_SET. If no safe patch can satisfy the "
        "objective and acceptance criteria, report a blocker instead of claiming success. "
        "Do NOT commit; the deterministic Agent Office integration boundary will create the "
        "candidate commit.\n\n"
        f"TASK_ID={lease.task_id}\n"
        f"DELEGATION_ID={lease.delegation_id}\n"
        f"BASE_SHA={lease.base_sha}\n"
        f"WRITE_SET={json.dumps(lease.write_set)}\n"
        f"READ_SET={json.dumps(lease.read_set)}\n"
        f"ALLOWED_TOOLS={json.dumps(lease.allowed_tools)}\n"
        f"ACCEPTANCE_CRITERIA={json.dumps(lease.acceptance_criteria)}\n"
        f"EXPECTED_OUTPUTS={json.dumps(lease.expected_outputs)}\n"
        f"OBJECTIVE={task.objective}\n"
        "Return a concise engineering summary only after local validation. "
        "When the objective or acceptance criteria require a measurable improvement, "
        "measure the same metric before and after the candidate using local allowed tools. "
        "Your FINAL message must end with exactly one line BR_METRIC_JSON=<json> containing "
        "metric_name, numeric baseline, numeric candidate, unit, direction "
        "(LOWER_IS_BETTER or HIGHER_IS_BETTER), and measurement_command. "
        "Do not invent measurements; if measurement cannot be produced, state the blocker "
        "instead of fabricating a metric."
    )
    command = [
        "codex",
        *provider_args,
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
    failure = codex_execution_failure(
        completed,
        failure_stage="bounded_development_exec",
    )
    if failure is not None:
        return failure

    observed_commands = _commands(completed.stdout)
    if len(observed_commands) > lease.tool_call_budget:
        raise RuntimeError("Codex exceeded tool_call_budget")
    for observed in observed_commands:
        _validate_command(observed, lease.allowed_tools)

    final_text = _final_text(completed.stdout)
    metric = _structured_metric(final_text)
    measurement_required = _measurement_required(task, lease)
    if measurement_required and metric is None:
        raise RuntimeError(
            "measurable bounded-development task produced no structured before/after metric"
        )
    if measurement_required and metric is not None and not metric["improved"]:
        raise RuntimeError(
            "measurable bounded-development candidate did not improve the declared metric"
        )

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
        "summary": final_text or "Codex bounded candidate created",
        "performance_evidence": metric,
        "measurement_required": measurement_required,
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
            "BENCHMARK_RESULTS": [metric] if metric is not None else [],
            "ARTIFACT_REFS": [f"candidate-commit:{candidate_sha}"],
            "EVIDENCE_REFS": [f"delegation:{lease.delegation_id}"],
            "WARNINGS": [],
            "ESCALATIONS": [],
            "CANDIDATE_READY_FOR_INTEGRATION": True,
        },
        "canonical_push_authority": "NONE",
        "worktree_isolation": "PASS",
        "codex_auth_method": (
            CODEX_TUXEVIL_AUTH_MODE
            if provider_args
            else "EXISTING_CODEX_LOGIN"
        ),
        "codex_responses_endpoint": (
            "TUXEVIL_LOOPBACK" if provider_args else "DEFAULT"
        ),
    }
