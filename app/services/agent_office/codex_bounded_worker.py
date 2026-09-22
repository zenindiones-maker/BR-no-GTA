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
MAX_CANDIDATE_REPAIR_PASSES = 1

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


def _agent_message_metric_stats(stdout: str) -> tuple[int, int]:
    message_count = 0
    metric_marker_count = 0
    for line in str(stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        message_count += 1
        metric_marker_count += text.count("BR_METRIC_JSON=")
    return message_count, metric_marker_count


def _bounded_repair_text(value: str, *, limit: int = 1800) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        return ""
    return normalized[:limit]


def _bounded_repair_commands(
    commands: tuple[str, ...],
    *,
    max_items: int = 8,
    max_chars: int = 240,
) -> tuple[str, ...]:
    return tuple(
        _bounded_repair_text(command, limit=max_chars)
        for command in commands[-max_items:]
        if _bounded_repair_text(command, limit=max_chars)
    )


_REPOSITORY_PATH_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:app|scripts|tests|config|integrations|\.github/workflows)"
    r"/[A-Za-z0-9_./-]+)"
)


def _grounded_writable_targets(
    *,
    task: AgentOfficeTask,
    lease: DelegatedTaskLease,
    workspace: Path,
    max_items: int = 8,
) -> tuple[str, ...]:
    source = "\n".join(
        [
            task.objective,
            *lease.acceptance_criteria,
            *lease.expected_outputs,
            *lease.evidence_requirements,
        ]
    )
    targets: list[str] = []
    for match in _REPOSITORY_PATH_TOKEN_RE.finditer(source):
        candidate = match.group(1).rstrip(".,:;)]}")
        if candidate in targets:
            continue
        if not lease.allows_path(candidate, write=True):
            continue
        if not (workspace / candidate).exists():
            continue
        targets.append(candidate)
        if len(targets) >= max_items:
            break
    return tuple(targets)


def _candidate_repair_context(
    *,
    task: AgentOfficeTask,
    lease: DelegatedTaskLease,
    workspace: Path,
    initial_final_text: str,
    initial_commands: tuple[str, ...],
) -> dict[str, Any]:
    summary = _bounded_repair_text(initial_final_text)
    commands = _bounded_repair_commands(initial_commands)
    targets = _grounded_writable_targets(
        task=task,
        lease=lease,
        workspace=workspace,
    )
    actionable = bool(targets and (summary or commands))
    return {
        "initial_pass_summary": summary,
        "initial_observed_commands": commands,
        "grounded_writable_targets": targets,
        "actionable": actionable,
    }


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


_SHELL_WRAPPER_TOOLS = {"bash", "sh"}
_SHELL_OPERATORS = {"&&", "||", ";", "|"}
_TOOL_ALIASES = {
    "python3": "python",
}


def canonical_command_tool(value: str) -> str:
    raw = Path(str(value or "")).name
    return _TOOL_ALIASES.get(raw, raw)


_SAFE_SED_PRINT_SCRIPT_RE = re.compile(
    r"^(?:(?:\d+|\$)(?:,(?:\d+|\$))?|/[^\n/]{1,240}/)p$"
)


def _validate_readonly_sed(parts: list[str]) -> None:
    args = parts[1:]
    if not args:
        raise PermissionError("sed command is outside the read-only inspection contract")
    if any(
        arg == "-i"
        or arg.startswith("-i")
        or arg == "--in-place"
        or arg.startswith("--in-place=")
        or arg in {"-f", "--file"}
        for arg in args
    ):
        raise PermissionError("sed mutation/script-file mode is forbidden")

    quiet = False
    scripts: list[str] = []
    paths: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-n", "--quiet", "--silent"}:
            quiet = True
            index += 1
            continue
        if arg in {"-e", "--expression"}:
            if index + 1 >= len(args):
                raise PermissionError("sed expression is missing")
            scripts.append(args[index + 1].strip())
            index += 2
            continue
        if arg.startswith("-"):
            raise PermissionError("sed option is outside the read-only inspection contract")
        if not scripts:
            scripts.append(arg.strip())
        else:
            paths.append(arg)
        index += 1

    if not quiet or not scripts or not paths:
        raise PermissionError("sed must use quiet print-only inspection with explicit paths")
    if any(not _SAFE_SED_PRINT_SCRIPT_RE.fullmatch(script) for script in scripts):
        raise PermissionError("sed script is outside the read-only print contract")




def _shell_segments(script: str) -> tuple[tuple[str, ...], ...]:
    if any(marker in script for marker in ("$(", chr(96), "<(", ">(")):
        raise PermissionError(
            "Codex shell wrapper attempted command/process substitution"
        )
    lexer = shlex.shlex(
        script,
        posix=True,
        punctuation_chars=";&|",
    )
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    if not tokens:
        return ()

    segments: list[tuple[str, ...]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SHELL_OPERATORS:
            if not current:
                raise PermissionError("Codex shell wrapper contains empty command")
            segments.append(tuple(current))
            current = []
            continue
        if token == "&":
            raise PermissionError("Codex shell wrapper attempted background execution")
        current.append(token)
    if not current:
        raise PermissionError("Codex shell wrapper ends with an operator")
    segments.append(tuple(current))
    return tuple(segments)

def _validate_command(command: str, allowed_tools: tuple[str, ...]) -> None:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise PermissionError("Codex emitted an unparsable command") from exc
    if not parts:
        return
    raw_tool = Path(parts[0]).name
    tool = canonical_command_tool(raw_tool)
    normalized = " ".join(parts)
    if tool in _FORBIDDEN_COMMANDS:
        raise PermissionError(f"Codex attempted forbidden command: {raw_tool}")
    if re.search(r"(?<![A-Za-z0-9_-])(?:curl|wget|ssh|scp|rsync|gh|docker|podman)(?![A-Za-z0-9_-])", normalized):
        raise PermissionError("Codex attempted forbidden external/network command")
    if re.search(r"(?<![A-Za-z0-9_-])git\s+(?:push|pull|fetch|merge|rebase|remote)(?![A-Za-z0-9_-])", normalized):
        raise PermissionError("Codex attempted forbidden git side effect")
    if tool in _SHELL_WRAPPER_TOOLS:
        if len(parts) != 3 or parts[1] not in {"-lc", "-c"}:
            raise PermissionError(
                "Codex shell wrapper is outside the bounded wrapper contract"
            )
        for segment in _shell_segments(parts[2]):
            _validate_command(shlex.join(segment), allowed_tools)
        return
    if tool not in allowed_tools:
        raise PermissionError(f"Codex command is outside COMMAND_ALLOWLIST: {tool}")
    if tool == "sed":
        _validate_readonly_sed(parts)
        return


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
        f"EVIDENCE_REQUIREMENTS={json.dumps(lease.evidence_requirements)}\n"
        f"OBJECTIVE={task.objective}\n"
        "MUTATION_REQUIRED=true\n"
        "A successful bounded-development task MUST leave at least one real working-tree "
        "change inside WRITE_SET before returning. Analysis-only success is invalid. "
        "If the objective leaves multiple safe options, choose the smallest evidence-backed "
        "change that satisfies the acceptance criteria without widening scope. "
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

    changed = _changed_paths(workspace, lease.base_sha)
    candidate_repair_used = False
    candidate_repair_context: dict[str, Any] | None = None
    final_text = _final_text(completed.stdout)
    if not changed:
        candidate_repair_context = _candidate_repair_context(
            task=task,
            lease=lease,
            workspace=workspace,
            initial_final_text=final_text,
            initial_commands=observed_commands,
        )
        if not candidate_repair_context["actionable"]:
            raise RuntimeError(
                "Codex bounded-development no-op lacks grounded candidate repair context"
            )
        candidate_repair_used = True
        if MAX_CANDIDATE_REPAIR_PASSES != 1:
            raise RuntimeError("candidate repair pass budget drifted from one")
        if len(observed_commands) >= lease.tool_call_budget:
            raise RuntimeError("Codex exceeded tool_call_budget")
        candidate_repair_prompt = (
            "NO_CANDIDATE_PATCH_DETECTED. The previous bounded-development pass "
            "returned without any working-tree change, so it did not satisfy the "
            "authorized mutation contract. This is the ONE allowed candidate-repair "
            "pass. Continue inside the SAME lease and SAME disposable worktree. "
            "Do not repeat discovery that is already present in INITIAL_PASS_SUMMARY "
            "or INITIAL_OBSERVED_COMMANDS. Use that prior analysis as continuity, then "
            "apply the smallest evidence-backed real change to one of "
            "GROUNDED_WRITABLE_TARGETS. Before returning, run an allowlisted local "
            "check that proves the working tree differs from BASE_SHA. Analysis-only "
            "success is invalid. Do not commit; the deterministic Agent Office boundary "
            "will create the candidate commit. Do not widen scope, change authority/"
            "policy, access secrets, use network tools, publish, deploy, push, merge, "
            "fetch, checkout, reset, or stash. If the grounded evidence is insufficient "
            "or no safe change satisfies the objective, report a blocker rather than "
            "claiming success.\n\n"
            f"TASK_ID={lease.task_id}\n"
            f"DELEGATION_ID={lease.delegation_id}\n"
            f"BASE_SHA={lease.base_sha}\n"
            f"WRITE_SET={json.dumps(lease.write_set)}\n"
            f"READ_SET={json.dumps(lease.read_set)}\n"
            f"ALLOWED_TOOLS={json.dumps(lease.allowed_tools)}\n"
            f"ACCEPTANCE_CRITERIA={json.dumps(lease.acceptance_criteria)}\n"
            f"EXPECTED_OUTPUTS={json.dumps(lease.expected_outputs)}\n"
            f"EVIDENCE_REQUIREMENTS={json.dumps(lease.evidence_requirements)}\n"
            f"OBJECTIVE={task.objective}\n"
            "INITIAL_PASS_SUMMARY="
            + json.dumps(candidate_repair_context["initial_pass_summary"])
            + "\nINITIAL_OBSERVED_COMMANDS="
            + json.dumps(candidate_repair_context["initial_observed_commands"])
            + "\nGROUNDED_WRITABLE_TARGETS="
            + json.dumps(candidate_repair_context["grounded_writable_targets"])
            + "\nMUTATION_REQUIRED=true"
        )
        candidate_repair_command = [
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
            candidate_repair_prompt,
        ]
        candidate_repair = _run(
            candidate_repair_command,
            cwd=workspace,
            timeout=remaining(),
            sanitized_env=True,
        )
        candidate_repair_failure = codex_execution_failure(
            candidate_repair,
            failure_stage="bounded_development_candidate_repair",
        )
        if candidate_repair_failure is not None:
            return candidate_repair_failure

        candidate_repair_commands = _commands(candidate_repair.stdout)
        if len(observed_commands) + len(candidate_repair_commands) > lease.tool_call_budget:
            raise RuntimeError("Codex exceeded tool_call_budget")
        for observed in candidate_repair_commands:
            _validate_command(observed, lease.allowed_tools)
        observed_commands = (*observed_commands, *candidate_repair_commands)
        changed = _changed_paths(workspace, lease.base_sha)
        if not changed:
            raise RuntimeError(
                "Codex bounded-development candidate repair produced no candidate patch"
                f"; initial_commands={len(candidate_repair_context['initial_observed_commands'])}"
                f"; repair_commands={len(candidate_repair_commands)}"
                f"; grounded_targets={len(candidate_repair_context['grounded_writable_targets'])}"
            )
        candidate_repair_text = _final_text(candidate_repair.stdout)
        if candidate_repair_text:
            final_text = candidate_repair_text

    outside = tuple(path for path in changed if not lease.allows_path(path, write=True))
    if outside:
        raise PermissionError(f"Codex changed paths outside lease: {outside}")

    metric = _structured_metric(final_text)
    measurement_required = _measurement_required(task, lease)
    metric_repair_used = False
    if measurement_required and metric is None:
        metric_repair_used = True
        repair_prompt = (
            "You are performing one bounded measurement-repair pass for an existing "
            "candidate. The candidate patch is frozen: DO NOT edit, write, commit, "
            "checkout, reset, stash, or otherwise mutate repository files. Use only "
            "read-only inspection/benchmark commands from ALLOWED_TOOLS. Compare the "
            "actual BASE_SHA state with the current candidate state and measure one "
            "real metric that directly demonstrates whether the candidate improved "
            "the objective. Do not invent values. If a real before/after measurement "
            "cannot be produced, say so without fabricating evidence. Your FINAL "
            "message must end with exactly one line BR_METRIC_JSON=<json> containing "
            "metric_name, numeric baseline, numeric candidate, unit, direction "
            "(LOWER_IS_BETTER or HIGHER_IS_BETTER), and measurement_command.\n\n"
            f"BASE_SHA={lease.base_sha}\n"
            f"CHANGED_PATHS={json.dumps(changed)}\n"
            f"READ_SET={json.dumps(lease.read_set)}\n"
            f"ALLOWED_TOOLS={json.dumps(lease.allowed_tools)}\n"
            f"OBJECTIVE={task.objective}\n"
            f"ACCEPTANCE_CRITERIA={json.dumps(lease.acceptance_criteria)}"
        )
        repair_command = [
            "codex",
            *provider_args,
            *CODEX_SHELL_ENVIRONMENT_POLICY_ARGS,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--color", "never",
            "--json",
            "--sandbox", "read-only",
            "-C", str(workspace),
            repair_prompt,
        ]
        repair = _run(
            repair_command,
            cwd=workspace,
            timeout=remaining(),
            sanitized_env=True,
        )
        repair_failure = codex_execution_failure(
            repair,
            failure_stage="bounded_development_metric_repair",
        )
        if repair_failure is not None:
            return repair_failure

        repair_commands = _commands(repair.stdout)
        if len(observed_commands) + len(repair_commands) > lease.tool_call_budget:
            raise RuntimeError("Codex exceeded tool_call_budget")
        for observed in repair_commands:
            _validate_command(observed, lease.allowed_tools)

        changed_after_repair = _changed_paths(workspace, lease.base_sha)
        if changed_after_repair != changed:
            raise PermissionError(
                "bounded metric repair mutated the frozen candidate"
            )
        repair_text = _final_text(repair.stdout)
        metric = _structured_metric(repair_text)
        if metric is None:
            initial_messages, initial_markers = _agent_message_metric_stats(
                completed.stdout
            )
            repair_messages, repair_markers = _agent_message_metric_stats(
                repair.stdout
            )
            raise RuntimeError(
                "measurable bounded-development task produced no structured before/after metric"
                f"; initial_agent_messages={initial_messages}; "
                f"initial_metric_markers={initial_markers}; "
                f"repair_agent_messages={repair_messages}; "
                f"repair_metric_markers={repair_markers}"
            )
        observed_commands = (*observed_commands, *repair_commands)

    if measurement_required and metric is not None and not metric["improved"]:
        raise RuntimeError(
            "measurable bounded-development candidate did not improve the declared metric"
        )

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
        "candidate_repair_used": candidate_repair_used,
        "candidate_repair_context_grounded_targets": list(
            (candidate_repair_context or {}).get("grounded_writable_targets") or ()
        ),
        "metric_repair_used": metric_repair_used,
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
