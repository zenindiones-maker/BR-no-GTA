from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
from typing import Any, Mapping

from app.services.agent_office.contracts import AgentOfficeTask
from app.services.agent_office.delegation import DelegatedTaskLease
from app.services.performance_telemetry_service import PerformanceSpan

CODEX_BOUNDED_DEVELOPMENT_CAPABILITY = "agent-office.codex.bounded-development"
MAX_CANDIDATE_REPAIR_PASSES = 1

CODEX_TUXEVIL_AUTH_MODE = "TUXEVIL_ANTIGRAVITY_RESPONSES_PROXY"
_CODEX_TUXEVIL_DEFAULT_BASE_URL = "http://127.0.0.1:51200/v1"
_CODEX_TUXEVIL_DEFAULT_MODEL = "gemini-3-flash"
_CODEX_TUXEVIL_LOOPBACK_KEY_ENV = "BR_TUXEVIL_LOOPBACK_KEY"
_SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class CodexBoundedWorkerFailure(RuntimeError):
    """Typed bounded-worker failure with explicit retry semantics."""

    retryability = "DETERMINISTIC_NO_RETRY"
    recoverable = False


class CodexDeterministicFailure(CodexBoundedWorkerFailure):
    retryability = "DETERMINISTIC_NO_RETRY"


class CodexReplanRequiredFailure(CodexBoundedWorkerFailure):
    retryability = "REPLAN_REQUIRED"


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
    tool = Path(str(command[0] if command else "unknown")).name or "unknown"
    category = (
        "AI_PROVIDER_TIME"
        if tool == "codex"
        else "REPOSITORY_IO_TIME"
        if tool == "git"
        else "SUBPROCESS_TIME"
    )
    provider = "codex" if tool == "codex" else None
    prompt_bytes = (
        len(str(command[-1]).encode("utf-8"))
        if tool == "codex" and command
        else None
    )
    with PerformanceSpan(
        stage=f"agent-office.bounded.subprocess.{tool}",
        category=category,
        provider=provider,
        model=(
            str(os.environ.get("BR_CODEX_TUXEVIL_MODEL") or "").strip() or None
            if tool == "codex"
            else None
        ),
        input_size=prompt_bytes,
        metadata={
            "tool": tool,
            "sanitized_env": bool(sanitized_env),
        },
    ) as span:
        completed = subprocess.run(
            command,
            cwd=cwd,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
            env=codex_sanitized_environment() if sanitized_env else None,
        )
        metadata = {
            "tool": tool,
            "returncode": int(completed.returncode),
        }
        parser = globals().get("_commands")
        if tool == "codex" and callable(parser):
            observed = tuple(parser(completed.stdout))
            metadata["tool_call_count"] = len(observed)
            metadata["unique_command_count"] = len(set(observed))
            metadata["duplicate_command_count"] = len(observed) - len(set(observed))
        span.set(
            output_size=len((completed.stdout or "").encode("utf-8")),
            metadata=metadata,
        )
        return completed

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


_REJECTED_COMMAND_SHAPE_SCHEMA = "codex-rejected-command/v1"
_ASSIGNMENT_LIKE_TOKEN_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$",
    re.DOTALL,
)
_SENSITIVE_TOKEN_PREFIX_RE = re.compile(
    r"^(?:gh[pousr]_|github_pat_|sk-|AIza)[A-Za-z0-9_.-]{8,}$",
    re.I,
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|cookie|token|secret|password|credential|api[_-]?key)",
    re.I,
)


def _redact_path_prefix(value: str, root: str | Path | None, marker: str) -> str:
    if not root:
        return value
    try:
        root_text = str(Path(root).resolve())
    except (OSError, RuntimeError):
        root_text = str(root)
    if not root_text:
        return value
    if value == root_text:
        return marker
    prefix = root_text.rstrip(os.sep) + os.sep
    if value.startswith(prefix):
        return marker + os.sep + value[len(prefix):]
    return value


def _sanitize_command_token(
    token: str,
    *,
    workspace: Path | None = None,
) -> str:
    value = str(token or "")
    assignment = _ASSIGNMENT_LIKE_TOKEN_RE.fullmatch(value)
    if assignment:
        return f"{assignment.group('name')}=<redacted>"

    if ":" in value:
        key, _separator, _rest = value.partition(":")
        if _SENSITIVE_KEY_RE.search(key):
            return f"{key}:<redacted>"
    if _SENSITIVE_TOKEN_PREFIX_RE.fullmatch(value):
        return "<redacted-sensitive-token>"

    value = _redact_path_prefix(value, workspace, "<WORKTREE>")
    value = _redact_path_prefix(
        value,
        os.environ.get("RUNNER_TEMP"),
        "<RUNNER_TEMP>",
    )
    value = _redact_path_prefix(value, Path.home(), "<HOME>")
    return value


def _first_token_kind(token: str) -> str:
    if not token:
        return "OTHER"
    if _ASSIGNMENT_LIKE_TOKEN_RE.fullmatch(token):
        return "ASSIGNMENT_LIKE"
    if Path(token).is_absolute():
        return "ABSOLUTE_PATH"
    if "/" in token or token.startswith("."):
        return "RELATIVE_PATH"
    if re.fullmatch(r"[A-Za-z0-9_.+-]+", token):
        return "BARE"
    return "OTHER"


def _rejected_command_shape(
    command: str,
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    raw = str(command or "")
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = []

    first_token = parts[0] if parts else (
        raw.lstrip().split(maxsplit=1)[0] if raw.strip() else ""
    )
    first_kind = _first_token_kind(first_token)
    canonical = canonical_command_tool(first_token) if first_token else ""

    wrapper = "NONE"
    if len(parts) >= 2:
        wrapper_tool = canonical_command_tool(parts[0])
        wrapper_mode = parts[1]
        if wrapper_tool in _SHELL_WRAPPER_TOOLS and wrapper_mode in {"-c", "-lc"}:
            wrapper = f"{wrapper_tool}-{'lc' if wrapper_mode == '-lc' else 'c'}"

    resolves = "NOT_CHECKED"
    if first_kind == "BARE" and first_token:
        sanitized_path = codex_sanitized_environment().get("PATH") or ""
        resolves = (
            "YES"
            if shutil.which(first_token, path=sanitized_path) is not None
            else "NO"
        )

    return {
        "COMMAND_SHAPE_SCHEMA": _REJECTED_COMMAND_SHAPE_SCHEMA,
        "CANONICAL_TOOL": _sanitize_command_token(
            canonical,
            workspace=workspace,
        ),
        "RAW_FIRST_TOKEN": _sanitize_command_token(
            first_token,
            workspace=workspace,
        ),
        "FIRST_TOKEN_KIND": first_kind,
        "FIRST_TOKEN_HAS_EQUALS": "YES" if "=" in first_token else "NO",
        "TOKEN_COUNT": len(parts),
        "SHELL_WRAPPER": wrapper,
        "HAS_COMMAND_SUBSTITUTION": (
            "YES" if "$(" in raw or "`" in raw else "NO"
        ),
        "HAS_PROCESS_SUBSTITUTION": (
            "YES" if "<(" in raw or ">(" in raw else "NO"
        ),
        "HAS_PIPE": (
            "YES" if re.search(r"(?<!\|)\|(?!\|)", raw) else "NO"
        ),
        "HAS_REDIRECTION": (
            "YES"
            if re.search(r"(?:^|[^<>])(?:>>?|<<)(?![<(])", raw)
            else "NO"
        ),
        "HAS_SHELL_OPERATOR": (
            "YES"
            if any(marker in raw for marker in ("&&", "||", ";", "|", "&"))
            else "NO"
        ),
        "ASSIGNMENT_LIKE_TOKEN_COUNT": sum(
            1 for token in parts
            if _ASSIGNMENT_LIKE_TOKEN_RE.fullmatch(token)
        ),
        "RESOLVES_ON_SANITIZED_PATH": resolves,
        "WORKTREE_PATHS_REDACTED": "YES",
        "SECRET_VALUES_REDACTED": "YES",
        "COMMAND_SHA256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def _persist_rejected_command_shape(
    command: str,
    *,
    workspace: Path | None = None,
) -> None:
    raw_path = str(
        os.environ.get("BR_REJECTED_COMMAND_EVIDENCE_PATH") or ""
    ).strip()
    if not raw_path:
        return

    path = Path(raw_path)
    try:
        # The first/deepest rejection is the causally useful command shape.
        # Recursive shell-wrapper validation must not overwrite it with the
        # outer wrapper after the inner command has already failed.
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _rejected_command_shape(command, workspace=workspace)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except (OSError, RuntimeError, ValueError):
        # Observability must never authorize, mask, or replace the original
        # command-validation failure.
        return


_TOOL_BUDGET_SCHEMA = "codex-tool-budget/v1"
_READ_ONLY_TOOL_NAMES = {"rg", "cat", "ls", "head", "wc", "sed"}
_READ_ONLY_GIT_SUBCOMMANDS = {
    "status", "diff", "show", "log", "grep", "rev-parse", "ls-files",
}
_VALIDATION_PYTHON_RE = re.compile(
    r"(?:^|\s)(?:-m\s+pytest|pytest|unittest|py_compile|compileall)(?:\s|$)"
)


def _sanitized_tool_name(command: str) -> str:
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        return "UNPARSABLE"
    if not parts:
        return "EMPTY"
    tool = canonical_command_tool(parts[0])
    sanitized = _sanitize_command_token(tool)
    if _SENSITIVE_KEY_RE.search(sanitized):
        return "<redacted-sensitive-tool>"
    if len(sanitized) > 128:
        return "sha256:" + hashlib.sha256(
            sanitized.encode("utf-8")
        ).hexdigest()[:16]
    return sanitized


def _tool_call_category(command: str) -> str:
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        return "WRITE_ATTEMPT"
    if not parts:
        return "READ_ONLY"

    tool = canonical_command_tool(parts[0])
    normalized = " ".join(parts)

    if tool == "pytest":
        return "VALIDATION"
    if tool == "python" and _VALIDATION_PYTHON_RE.search(normalized):
        return "VALIDATION"
    if tool in _READ_ONLY_TOOL_NAMES:
        return "READ_ONLY"
    if tool == "git" and len(parts) >= 2 and parts[1] in _READ_ONLY_GIT_SUBCOMMANDS:
        return "READ_ONLY"

    if tool in _SHELL_WRAPPER_TOOLS and len(parts) == 3 and parts[1] in {"-c", "-lc"}:
        try:
            segments = _shell_segments(parts[2])
        except PermissionError:
            return "WRITE_ATTEMPT"
        categories = tuple(
            _tool_call_category(shlex.join(segment))
            for segment in segments
        )
        if categories and all(item == "READ_ONLY" for item in categories):
            return "READ_ONLY"
        if categories and all(
            item in {"READ_ONLY", "VALIDATION"} for item in categories
        ) and "VALIDATION" in categories:
            return "VALIDATION"
    return "WRITE_ATTEMPT"


def _sanitized_command_fingerprint(command: str) -> str:
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        normalized = "<unparsable-command>"
    else:
        normalized = shlex.join(
            [_sanitize_command_token(token) for token in parts]
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _operation_class(command: str) -> str:
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        return "other"
    if not parts:
        return "other"
    tool = canonical_command_tool(parts[0])
    normalized = " ".join(parts)
    if tool in _SHELL_WRAPPER_TOOLS and len(parts) == 3 and parts[1] in {"-c", "-lc"}:
        try:
            segments = _shell_segments(parts[2])
        except PermissionError:
            return "other"
        classes = {_operation_class(shlex.join(segment)) for segment in segments}
        return next(iter(classes)) if len(classes) == 1 else "other"
    if tool == "git":
        return "git_read" if len(parts) >= 2 and parts[1] in _READ_ONLY_GIT_SUBCOMMANDS else "write"
    if tool == "rg":
        return "repo_search"
    if tool in {"cat", "head", "sed", "ls"}:
        return "file_read"
    if tool == "wc":
        return "measurement"
    if tool == "pytest" or (
        tool == "python" and _VALIDATION_PYTHON_RE.search(normalized)
    ):
        return "test"
    if _tool_call_category(command) == "WRITE_ATTEMPT":
        return "write"
    return "other"


def _tool_budget_evidence(
    *,
    task: AgentOfficeTask,
    lease: DelegatedTaskLease,
    terminal_status: str,
    evidence_trigger: str,
    terminal_stage: str,
    initial_commands: tuple[str, ...] = (),
    candidate_repair_commands: tuple[str, ...] = (),
    final_validation_commands: tuple[str, ...] = (),
    retry_commands: tuple[str, ...] = (),
    candidate_repair_used: bool = False,
    budget_check_mode: str = "TERMINAL_SNAPSHOT",
) -> dict[str, Any]:
    stages = (
        tuple(initial_commands),
        tuple(candidate_repair_commands),
        tuple(final_validation_commands),
        tuple(retry_commands),
    )
    commands = tuple(command for stage in stages for command in stage)
    total = len(commands)
    budget = int(lease.tool_call_budget)

    if terminal_status not in {"SUCCESS", "TOOL_BUDGET_EXCEEDED"}:
        raise ValueError("unsupported tool-budget terminal status")
    if evidence_trigger not in {"TERMINAL_SUCCESS", "FAIL_CLOSED_BUDGET"}:
        raise ValueError("unsupported tool-budget evidence trigger")

    tool_counts: dict[str, int] = {}
    category_counts = {
        "READ_ONLY": 0,
        "WRITE_ATTEMPT": 0,
        "VALIDATION": 0,
    }
    command_hashes: list[str] = []
    duplicate_groups: dict[tuple[str, str, str], int] = {}
    stage_commands = (
        ("initial", tuple(initial_commands)),
        ("candidate_repair", tuple(candidate_repair_commands)),
        ("final_validation", tuple(final_validation_commands)),
        ("retry", tuple(retry_commands)),
    )
    for stage_name, stage_items in stage_commands:
        for command in stage_items:
            fingerprint = _sanitized_command_fingerprint(command)
            operation_class = _operation_class(command)
            key = (stage_name, operation_class, fingerprint)
            duplicate_groups[key] = duplicate_groups.get(key, 0) + 1
    for command in commands:
        tool = _sanitized_tool_name(command)
        tool_counts[tool] = tool_counts.get(tool, 0) + 1
        category = _tool_call_category(command)
        category_counts[category] = category_counts.get(category, 0) + 1
        command_hashes.append(
            hashlib.sha256(str(command).encode("utf-8")).hexdigest()
        )

    unique_count = len(set(command_hashes))
    return {
        "TOOL_BUDGET_SCHEMA": _TOOL_BUDGET_SCHEMA,
        "TASK_ID": (
            str(task.task_id)
            if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", str(task.task_id))
            else "sha256:" + hashlib.sha256(
                str(task.task_id).encode("utf-8")
            ).hexdigest()[:16]
        ),
        "CAPABILITY": CODEX_BOUNDED_DEVELOPMENT_CAPABILITY,
        "TERMINAL_STATUS": terminal_status,
        "EVIDENCE_TRIGGER": evidence_trigger,
        "TERMINAL_STAGE": terminal_stage,
        # Retained for compatibility with the failure-only v1 observer.
        "FAILURE_STAGE": (
            terminal_stage
            if terminal_status == "TOOL_BUDGET_EXCEEDED"
            else "NOT_APPLICABLE"
        ),
        "TOOL_CALL_BUDGET_ASSIGNED": budget,
        "TOOL_CALL_BUDGET": budget,
        "TOOL_CALL_COUNT_OBSERVED": total,
        "TOOL_CALL_OVERAGE": max(0, total - budget),
        "BUDGET_CHECK_MODE": str(budget_check_mode),
        "INITIAL_PASS_TOOL_CALLS": len(initial_commands),
        "CANDIDATE_REPAIR_TOOL_CALLS": len(candidate_repair_commands),
        "FINAL_VALIDATION_TOOL_CALLS": len(final_validation_commands),
        "RETRY_TOOL_CALLS": len(retry_commands),
        "RETRY_BUDGET_ASSIGNED": int(lease.retry_budget),
        "CANDIDATE_REPAIR_USED": "YES" if candidate_repair_used else "NO",
        "TOOL_COUNTS_BY_CANONICAL_TOOL": dict(sorted(tool_counts.items())),
        "COMMAND_GROUPS": [
            {
                "STAGE": stage,
                "OPERATION_CLASS": operation_class,
                "COMMAND_FINGERPRINT": fingerprint,
                "COUNT": count,
            }
            for (stage, operation_class, fingerprint), count
            in sorted(duplicate_groups.items())
        ],
        "DUPLICATE_GROUPING_SAFE": "PASS",
        "UNIQUE_COMMAND_COUNT": unique_count,
        "DUPLICATE_COMMAND_COUNT": total - unique_count,
        "READ_ONLY_CALL_COUNT": category_counts["READ_ONLY"],
        "WRITE_ATTEMPT_COUNT": category_counts["WRITE_ATTEMPT"],
        "VALIDATION_CALL_COUNT": category_counts["VALIDATION"],
        "TOOL_NAMES_SANITIZED": "YES",
        "RAW_COMMANDS_PERSISTED": "NO",
        "SECRET_LEAK": "NO",
    }


def _persist_tool_budget_evidence(
    *,
    task: AgentOfficeTask,
    lease: DelegatedTaskLease,
    terminal_status: str,
    evidence_trigger: str,
    terminal_stage: str,
    initial_commands: tuple[str, ...] = (),
    candidate_repair_commands: tuple[str, ...] = (),
    final_validation_commands: tuple[str, ...] = (),
    retry_commands: tuple[str, ...] = (),
    candidate_repair_used: bool = False,
    budget_check_mode: str = "TERMINAL_SNAPSHOT",
) -> None:
    raw_path = str(
        os.environ.get("BR_TOOL_BUDGET_EVIDENCE_PATH") or ""
    ).strip()
    if not raw_path:
        return

    path = Path(raw_path)
    try:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _tool_budget_evidence(
            task=task,
            lease=lease,
            terminal_status=terminal_status,
            evidence_trigger=evidence_trigger,
            terminal_stage=terminal_stage,
            initial_commands=initial_commands,
            candidate_repair_commands=candidate_repair_commands,
            final_validation_commands=final_validation_commands,
            retry_commands=retry_commands,
            candidate_repair_used=candidate_repair_used,
            budget_check_mode=budget_check_mode,
        )
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except (OSError, RuntimeError, ValueError):
        # Observability must never mask or replace worker behavior.
        return


def canonical_command_tool(value: str) -> str:
    raw = Path(str(value or "")).name
    return _TOOL_ALIASES.get(raw, raw)


_SAFE_SED_PRINT_SCRIPT_RE = re.compile(
    r"^(?:(?:\d+|\$)(?:,(?:\d+|\$))?|/[^\n/]{1,240}/)p$"
)


_SAFE_WC_MODES = {"-l", "-c", "-w"}
_SAFE_WC_PATH_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]{0,1023}$")


def _validate_readonly_wc(
    parts: list[str],
    *,
    lease: DelegatedTaskLease | None,
    workspace: Path | None,
) -> None:
    if lease is None or workspace is None:
        raise PermissionError("wc requires delegated TaskEnvelope scope")
    if len(parts) < 3 or parts[1] not in _SAFE_WC_MODES:
        raise PermissionError(
            "wc is limited to -l, -c, or -w with explicit scoped files"
        )

    root = workspace.resolve()
    for raw_path in parts[2:]:
        if (
            not raw_path
            or raw_path == "-"
            or raw_path.startswith("-")
            or raw_path.startswith("/")
            or not _SAFE_WC_PATH_RE.fullmatch(raw_path)
            or ".." in Path(raw_path).parts
        ):
            raise PermissionError("wc path is outside the bounded read contract")

        target = (root / raw_path).resolve()
        try:
            relative = target.relative_to(root).as_posix()
        except ValueError as exc:
            raise PermissionError(
                "wc path escapes the delegated worktree"
            ) from exc
        if not lease.allows_path(relative, write=False):
            raise PermissionError(
                "wc path is outside delegated TaskEnvelope read scope"
            )
        if not target.is_file():
            raise PermissionError(
                "wc requires an existing regular file in delegated scope"
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

def _validate_command_impl(
    command: str,
    allowed_tools: tuple[str, ...],
    *,
    lease: DelegatedTaskLease | None = None,
    workspace: Path | None = None,
) -> None:
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
    if re.search(
        r"(?<![A-Za-z0-9_-])(?:curl|wget|ssh|scp|rsync|gh|docker|podman)"
        r"(?![A-Za-z0-9_-])",
        normalized,
    ):
        raise PermissionError("Codex attempted forbidden external/network command")
    if re.search(
        r"(?<![A-Za-z0-9_-])git\s+"
        r"(?:push|pull|fetch|merge|rebase|remote)(?![A-Za-z0-9_-])",
        normalized,
    ):
        raise PermissionError("Codex attempted forbidden git side effect")
    if tool in _SHELL_WRAPPER_TOOLS:
        if len(parts) != 3 or parts[1] not in {"-lc", "-c"}:
            raise PermissionError(
                "Codex shell wrapper is outside the bounded wrapper contract"
            )
        segments = _shell_segments(parts[2])
        if re.search(r"(?<!\|)\|(?!\|)", parts[2]) and any(
            segment
            and canonical_command_tool(segment[0]) == "wc"
            for segment in segments
        ):
            raise PermissionError("wc pipelines are outside the bounded contract")
        for segment in segments:
            _validate_command(
                shlex.join(segment),
                allowed_tools,
                lease=lease,
                workspace=workspace,
            )
        return
    if tool not in allowed_tools:
        raise PermissionError(
            f"Codex command is outside COMMAND_ALLOWLIST: {tool}"
        )
    if tool == "sed":
        _validate_readonly_sed(parts)
        return
    if tool == "wc":
        _validate_readonly_wc(
            parts,
            lease=lease,
            workspace=workspace,
        )
        return



def _validate_command(
    command: str,
    allowed_tools: tuple[str, ...],
    *,
    lease: DelegatedTaskLease | None = None,
    workspace: Path | None = None,
) -> None:
    try:
        _validate_command_impl(
            command,
            allowed_tools,
            lease=lease,
            workspace=workspace,
        )
    except PermissionError:
        _persist_rejected_command_shape(
            command,
            workspace=workspace,
        )
        raise


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
    with PerformanceSpan(
        stage="agent-office.bounded.initial-pass",
        category="CODEX_INITIAL_PASS_TIME",
        task_id=task.task_id,
        agent_id=task.agent,
        capability_id=task.capability,
    ):
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

    initial_commands = _commands(completed.stdout)
    observed_commands = initial_commands
    candidate_repair_commands: tuple[str, ...] = ()
    final_validation_commands: tuple[str, ...] = ()
    retry_commands: tuple[str, ...] = ()
    if len(observed_commands) > lease.tool_call_budget:
        _persist_tool_budget_evidence(
            task=task,
            lease=lease,
            terminal_status="TOOL_BUDGET_EXCEEDED",
            evidence_trigger="FAIL_CLOSED_BUDGET",
            terminal_stage="INITIAL_PASS",
            initial_commands=initial_commands,
            candidate_repair_used=False,
            budget_check_mode="STRICT_OVERAGE",
        )
        raise CodexDeterministicFailure("Codex exceeded tool_call_budget")
    for observed in observed_commands:
        _validate_command(
            observed,
            lease.allowed_tools,
            lease=lease,
            workspace=workspace,
        )

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
            raise CodexReplanRequiredFailure(
                "Codex bounded-development no-op lacks grounded candidate repair context"
            )
        candidate_repair_used = True
        if MAX_CANDIDATE_REPAIR_PASSES != 1:
            raise CodexDeterministicFailure(
                "candidate repair pass budget drifted from one"
            )
        if len(observed_commands) >= lease.tool_call_budget:
            _persist_tool_budget_evidence(
                task=task,
                lease=lease,
                terminal_status="TOOL_BUDGET_EXCEEDED",
                evidence_trigger="FAIL_CLOSED_BUDGET",
                terminal_stage="CANDIDATE_REPAIR_PRECHECK",
                initial_commands=initial_commands,
                candidate_repair_used=False,
                budget_check_mode="REQUIRE_REMAINING_SLOT",
            )
            raise CodexDeterministicFailure("Codex exceeded tool_call_budget")
        mutation_guidance = (
            "AUTHORIZED_MUTATION_MECHANISM=Use the Codex native workspace-write "
            "editing primitive. If that primitive is unavailable and python is in "
            "ALLOWED_TOOLS, use one allowlisted python command to rewrite only a "
            "path listed in GROUNDED_WRITABLE_TARGETS. Do not use sed -i, shell "
            "redirection outside those targets, or any unallowlisted tool."
            if "python" in lease.allowed_tools
            else
            "AUTHORIZED_MUTATION_MECHANISM=Use only the Codex native workspace-write "
            "editing primitive on GROUNDED_WRITABLE_TARGETS; no shell mutation tool "
            "is authorized by this lease."
        )
        candidate_repair_prompt = (
            "NO_CANDIDATE_PATCH_DETECTED. The previous bounded-development pass "
            "returned without any working-tree change, so it did not satisfy the "
            "authorized mutation contract. This is the ONE allowed candidate-repair "
            "pass. Continue inside the SAME lease and SAME disposable worktree. "
            "Do not repeat discovery that is already present in INITIAL_PASS_SUMMARY "
            "or INITIAL_OBSERVED_COMMANDS. Use that prior analysis as continuity. "
            "The repair pass is action-first: choose one evidence-backed target from "
            "GROUNDED_WRITABLE_TARGETS and perform the smallest authorized mutation "
            "before doing any additional broad inspection. At most two read-only "
            "inspection commands may run before the first mutation attempt. Then run "
            "the narrowest allowlisted local validation needed by the acceptance "
            "criteria. Before returning, prove the working tree differs from BASE_SHA. "
            "Analysis-only success is invalid. Do not commit; the deterministic Agent "
            "Office boundary will create the candidate commit. Do not widen scope, "
            "change authority/policy, access secrets, use network tools, publish, "
            "deploy, push, merge, fetch, checkout, reset, or stash. If the grounded "
            "evidence is insufficient or no safe change satisfies the objective, "
            "report a blocker rather than claiming success.\n\n"
            + mutation_guidance
            + "\n"
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
        with PerformanceSpan(
            stage="agent-office.bounded.candidate-repair",
            category="CODEX_CANDIDATE_REPAIR_TIME",
            task_id=task.task_id,
            agent_id=task.agent,
            capability_id=task.capability,
        ):
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
            _persist_tool_budget_evidence(
                task=task,
                lease=lease,
                terminal_status="TOOL_BUDGET_EXCEEDED",
                evidence_trigger="FAIL_CLOSED_BUDGET",
                terminal_stage="CANDIDATE_REPAIR",
                initial_commands=initial_commands,
                candidate_repair_commands=candidate_repair_commands,
                candidate_repair_used=True,
                budget_check_mode="STRICT_OVERAGE",
            )
            raise CodexDeterministicFailure("Codex exceeded tool_call_budget")
        for observed in candidate_repair_commands:
            _validate_command(
            observed,
            lease.allowed_tools,
            lease=lease,
            workspace=workspace,
        )
        observed_commands = (*observed_commands, *candidate_repair_commands)
        changed = _changed_paths(workspace, lease.base_sha)
        if not changed:
            raise CodexReplanRequiredFailure(
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
        with PerformanceSpan(
            stage="agent-office.bounded.final-validation",
            category="CODEX_FINAL_VALIDATION_TIME",
            task_id=task.task_id,
            agent_id=task.agent,
            capability_id=task.capability,
        ):
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
        final_validation_commands = repair_commands
        if len(observed_commands) + len(repair_commands) > lease.tool_call_budget:
            _persist_tool_budget_evidence(
                task=task,
                lease=lease,
                terminal_status="TOOL_BUDGET_EXCEEDED",
                evidence_trigger="FAIL_CLOSED_BUDGET",
                terminal_stage="FINAL_VALIDATION",
                initial_commands=initial_commands,
                candidate_repair_commands=candidate_repair_commands,
                final_validation_commands=final_validation_commands,
                retry_commands=retry_commands,
                candidate_repair_used=candidate_repair_used,
                budget_check_mode="STRICT_OVERAGE",
            )
            raise CodexDeterministicFailure("Codex exceeded tool_call_budget")
        for observed in repair_commands:
            _validate_command(
            observed,
            lease.allowed_tools,
            lease=lease,
            workspace=workspace,
        )

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
            raise CodexReplanRequiredFailure(
                "measurable bounded-development task produced no structured before/after metric"
                f"; initial_agent_messages={initial_messages}; "
                f"initial_metric_markers={initial_markers}; "
                f"repair_agent_messages={repair_messages}; "
                f"repair_metric_markers={repair_markers}"
            )
        observed_commands = (*observed_commands, *repair_commands)

    if measurement_required and metric is not None and not metric["improved"]:
        raise CodexReplanRequiredFailure(
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
    _persist_tool_budget_evidence(
        task=task,
        lease=lease,
        terminal_status="SUCCESS",
        evidence_trigger="TERMINAL_SUCCESS",
        terminal_stage="BOUNDED_DEVELOPMENT_COMPLETE",
        initial_commands=initial_commands,
        candidate_repair_commands=candidate_repair_commands,
        final_validation_commands=final_validation_commands,
        retry_commands=retry_commands,
        candidate_repair_used=candidate_repair_used,
        budget_check_mode="TERMINAL_SNAPSHOT",
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
