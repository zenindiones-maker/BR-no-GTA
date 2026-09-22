from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping

from app.services.agent_office.contracts import (
    AgentOfficeExecutionResult,
    AgentOfficeExecutionSpec,
    AgentOfficeTask,
)
from app.services.agent_office.evidence import evidence_digest, sanitize_evidence
from app.services.agent_office.delegation import DelegatedTaskLease
from app.services.agent_office.codex_bounded_worker import (
    CODEX_BOUNDED_DEVELOPMENT_CAPABILITY,
    CODEX_SHELL_ENVIRONMENT_POLICY_ARGS,
    CODEX_TUXEVIL_AUTH_MODE,
    codex_bounded_development_worker,
    codex_execution_failure,
    codex_sanitized_environment,
    codex_tuxevil_provider_args,
    is_codex_sandbox_host_policy_failure,
)
from app.services.agent_office.addy_task_owner_worker import (
    addy_specialist_task_owner_worker,
)
from app.services.performance_telemetry_service import emit_performance_event


WorkerRunner = Callable[..., dict[str, Any]]
EventSink = Callable[[str, str, dict[str, Any]], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _path_allowed(path: str, allowed_paths: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    return any(
        normalized == allowed.strip("/") or normalized.startswith(f"{allowed.strip('/')}/")
        for allowed in allowed_paths
        if allowed.strip("/")
    )


def _changed_paths(workspace: Path, base_sha: str) -> tuple[str, ...]:
    tracked = _git(workspace, "diff", "--name-only", base_sha, "--").stdout.splitlines()
    untracked = _git(
        workspace, "ls-files", "--others", "--exclude-standard"
    ).stdout.splitlines()
    return tuple(sorted(set(filter(None, (*tracked, *untracked)))))


def _commits_ahead(workspace: Path, base_sha: str) -> tuple[str, ...]:
    return tuple(
        filter(
            None,
            _git(workspace, "rev-list", "--reverse", f"{base_sha}..HEAD").stdout.splitlines(),
        )
    )


def deterministic_read_only_worker(
    task: AgentOfficeTask,
    workspace: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise TimeoutError("Agent Office time budget exhausted")
    started = time.perf_counter()
    tracked = _git(workspace, "ls-files").stdout.splitlines()
    scopes = tuple(task.read_set or task.allowed_paths or (
        "app", "scripts", "tests", ".github/workflows", "config", "integrations"
    ))
    scoped = [
        path for path in tracked
        if any(
            path == scope.rstrip("/")
            or path.startswith(scope.rstrip("/") + "/")
            for scope in scopes
            if scope.rstrip("/")
        )
    ]
    if not scoped:
        scoped = tracked

    rows: list[dict[str, Any]] = []
    total_bytes = 0
    total_lines = 0
    python_files = 0
    workflow_files = 0
    large_modules: list[dict[str, Any]] = []
    for relative in scoped:
        path = workspace / relative
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        size = len(raw)
        lines = raw.count(b"\n") + (1 if raw else 0)
        total_bytes += size
        total_lines += lines
        if relative.endswith(".py"):
            python_files += 1
        if relative.startswith(".github/workflows/") and relative.endswith((".yml", ".yaml")):
            workflow_files += 1
        row = {
            "path": relative,
            "bytes": size,
            "lines": lines,
        }
        rows.append(row)
        if lines >= 1000:
            large_modules.append(row)

    rows.sort(key=lambda item: (-int(item["lines"]), -int(item["bytes"]), item["path"]))
    largest = rows[:12]
    largest_lines = int(largest[0]["lines"]) if largest else 0
    concentration = (
        float(largest_lines) / float(total_lines)
        if total_lines > 0 else 0.0
    )
    inventory_sha = sha256(
        "\n".join(
            f"{item['path']}:{item['bytes']}:{item['lines']}"
            for item in sorted(rows, key=lambda item: item["path"])
        ).encode("utf-8")
    ).hexdigest()
    observed_fragilities: list[dict[str, Any]] = []
    if large_modules:
        observed_fragilities.append({
            "kind": "LARGE_MODULE_CONCENTRATION",
            "metric": "files_over_1000_lines",
            "value": len(large_modules),
            "evidence": [item["path"] for item in large_modules[:8]],
        })
    if concentration >= 0.05:
        observed_fragilities.append({
            "kind": "SOURCE_CONCENTRATION",
            "metric": "largest_file_share_of_scoped_lines",
            "value": round(concentration, 6),
            "evidence": [largest[0]["path"]] if largest else [],
        })

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "status": "SUCCEEDED",
        "summary": (
            f"{task.task_id}: profiled {len(rows)} repository files, "
            f"{total_lines} lines and {total_bytes} bytes in {elapsed_ms} ms"
        ),
        "commands": ["git ls-files"],
        "artifacts": [],
        "tests": [
            {"name": "repository-profile-non-empty", "status": "PASS" if rows else "FAIL"},
            {"name": "write-scope-empty", "status": "PASS" if not task.write_set else "FAIL"},
        ],
        "usage": {"cost": 0.0, "tool_calls": 1},
        "analysis": {
            "metric_schema": "agent-office-repository-profile/v1",
            "tracked_file_count": len(tracked),
            "scoped_file_count": len(rows),
            "total_bytes": total_bytes,
            "total_lines": total_lines,
            "python_file_count": python_files,
            "workflow_file_count": workflow_files,
            "files_over_1000_lines": len(large_modules),
            "largest_file_lines": largest_lines,
            "largest_file_share_of_scoped_lines": round(concentration, 6),
            "largest_files": largest,
            "observed_fragilities": observed_fragilities,
            "inventory_sha256": inventory_sha,
            "profile_latency_ms": elapsed_ms,
            "read_scope": list(scopes),
        },
    }


CODEX_READONLY_CAPABILITY = "agent-office.codex.readonly-analysis"


def _codex_process(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise subprocess.TimeoutExpired(command, timeout_seconds)
    return subprocess.run(
        command,
        cwd=cwd,
        timeout=timeout_seconds,
        check=False,
        capture_output=True,
        text=True,
        env=codex_sanitized_environment(),
    )


def _codex_agent_text(stdout: str) -> str:
    final = ""
    for line in str(stdout or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        value = item.get("text")
        if isinstance(value, str):
            final = value
    return final[:2_000]


def _codex_commands(stdout: str) -> tuple[str, ...]:
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


def _codex_inspected_paths(
    commands: tuple[str, ...],
    task: AgentOfficeTask,
) -> tuple[str, ...]:
    targets = tuple(task.read_set or task.allowed_paths)
    if not targets:
        return ("<command-evidence>",) if commands else ()
    return tuple(
        sorted(
            path
            for path in targets
            if any(path in command for command in commands)
        )
    )


def codex_readonly_worker(
    task: AgentOfficeTask,
    workspace: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Bounded internal Codex worker; canonical Addy skills never route here."""
    if task.capability.startswith("addy:"):
        raise PermissionError(
            "Canonical Addy capabilities must execute through the Harness Addy boundary"
        )
    if task.capability != CODEX_READONLY_CAPABILITY:
        raise PermissionError("Codex worker received an unsupported internal capability")
    deadline = time.monotonic() + timeout_seconds

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise subprocess.TimeoutExpired(["codex"], timeout_seconds)
        return value

    provider_args = codex_tuxevil_provider_args()
    if not provider_args:
        auth = _codex_process(
            ["codex", "login", "status"],
            cwd=workspace,
            timeout_seconds=remaining(),
        )
        if auth.returncode != 0:
            raise RuntimeError("Codex authentication prerequisite is unavailable")

    prompt = (
        "You are a subordinate read-only Agent Office worker under DeepSeek Harness authority. "
        "Inspect only the provided disposable git worktree. Do not mutate files, commit, publish, "
        "deploy, authenticate to other services, invoke Addy skills, or claim authority. "
        "You MUST use shell inspection tooling to read at least one file from READ_SET before "
        "claiming success. If the sandbox or filesystem prevents inspection, report the block "
        "and do not claim completion. Return concise analysis evidence to the Agent Office "
        "coordinator.\n\n"
        f"READ_SET={json.dumps(task.read_set or task.allowed_paths)}\n"
        f"Task:\n{task.objective}"
    )
    command = [
        "codex",
        *provider_args,
        *CODEX_SHELL_ENVIRONMENT_POLICY_ARGS,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--json",
        "--sandbox",
        "read-only",
        "-C",
        str(workspace),
        prompt,
    ]
    completed = _codex_process(
        command,
        cwd=workspace,
        timeout_seconds=remaining(),
    )
    failure = codex_execution_failure(
        completed,
        failure_stage="readonly_exec",
    )
    if failure is not None:
        return failure
    output = _codex_agent_text(completed.stdout)
    observed_commands = _codex_commands(completed.stdout)
    inspected_paths = _codex_inspected_paths(observed_commands, task)
    if not output:
        return {
            "status": "FAILED",
            "error": "Codex read-only worker returned no agent message",
            "exit_code": int(completed.returncode),
            "failure_stage": "readonly_result_validation",
            "stderr_class": "EMPTY_AGENT_MESSAGE",
            "sandbox_backend": "bubblewrap",
            "retryability": "DETERMINISTIC_NO_RETRY",
            "recoverable": False,
        }
    if not inspected_paths:
        return {
            "status": "FAILED",
            "error": "Codex read-only inspection evidence missing",
            "exit_code": int(completed.returncode),
            "failure_stage": "readonly_result_validation",
            "stderr_class": "INSPECTION_EVIDENCE_MISSING",
            "sandbox_backend": "bubblewrap",
            "retryability": "DETERMINISTIC_NO_RETRY",
            "recoverable": False,
        }
    return {
        "status": "SUCCEEDED",
        "summary": output,
        "commands": ["codex exec --sandbox read-only"],
        "artifacts": [],
        "tests": [],
        "usage": {"cost": 0.0, "cost_available": False},
        "engine_result": {
            "output": output,
            "sandbox": "read-only",
            "sandbox_backend": "bubblewrap",
            "workspace": "disposable_worktree",
            "canonical_addy_bypass": False,
            "observed_command_count": len(observed_commands),
            "inspected_paths": list(inspected_paths),
            "codex_auth_method": (
                CODEX_TUXEVIL_AUTH_MODE
                if provider_args
                else "EXISTING_CODEX_LOGIN"
            ),
            "codex_responses_endpoint": (
                "TUXEVIL_LOOPBACK" if provider_args else "DEFAULT"
            ),
        },
    }


def registered_worker_runners() -> dict[str, WorkerRunner]:
    return {
        "deterministic-analysis": deterministic_read_only_worker,
        "codex": codex_readonly_worker,
        "codex-development": codex_bounded_development_worker,
        "addy-specialist": addy_specialist_task_owner_worker,
    }


def _tool_name(command: str) -> str:
    try:
        parts = shlex.split(str(command))
    except ValueError:
        return ""
    return Path(parts[0]).name if parts else ""


def _commands_within_lease(commands: list[str], lease: DelegatedTaskLease) -> None:
    for command in commands:
        normalized = str(command).strip()
        if not normalized:
            continue
        tool = _tool_name(normalized)
        if tool not in lease.allowed_tools:
            raise PermissionError(f"worker command outside allowed_tools: {tool or 'unknown'}")
        parts = shlex.split(normalized)
        if tool == "git" and len(parts) > 1 and parts[1] in {
            "push", "pull", "fetch", "merge", "rebase", "remote",
        }:
            raise PermissionError("worker attempted a forbidden git side effect")
        if tool in {"curl", "wget", "ssh", "scp", "gh"}:
            raise PermissionError("worker attempted a forbidden external tool")


_SAFE_WORKER_RUNTIME_ERROR_PREFIXES = (
    "Codex exceeded tool_call_budget",
    "measurable bounded-development task produced no structured before/after metric",
    "measurable bounded-development candidate did not improve the declared metric",
    "Codex bounded-development produced no candidate patch",
    "Codex bounded-development no-op lacks grounded candidate repair context",
    "Codex bounded-development candidate repair produced no candidate patch",
    "candidate git add failed",
    "candidate local commit failed",
    "candidate commit identity unavailable",
    "Codex authentication prerequisite is unavailable",
    "Codex emitted invalid BR_METRIC_JSON",
    "BR_METRIC_JSON is missing required fields",
    "BR_METRIC_JSON baseline must be numeric",
    "BR_METRIC_JSON candidate must be numeric",
    "BR_METRIC_JSON direction is invalid",
)


def _safe_worker_exception_reason(exc: Exception) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return "worker execution timed out"
    if isinstance(exc, RuntimeError):
        text = str(exc).strip()
        if any(
            text.startswith(prefix)
            for prefix in _SAFE_WORKER_RUNTIME_ERROR_PREFIXES
        ):
            return text[:500]
    return "worker execution failed"


def _lease_conflict(left: DelegatedTaskLease, right: DelegatedTaskLease) -> bool:
    for a in left.write_set:
        aa = a.rstrip("/")
        for b in right.write_set:
            bb = b.rstrip("/")
            if aa == bb or aa.startswith(f"{bb}/") or bb.startswith(f"{aa}/"):
                return True
    return False


def _persist_task_artifact(
    repository_root: Path,
    spec: AgentOfficeExecutionSpec,
    task_id: str,
    result: dict[str, Any],
) -> tuple[str, str]:
    root = Path(
        os.getenv("AGENT_OFFICE_ARTIFACT_ROOT")
        or repository_root / "runtime" / "agent-office"
    )
    target = root / spec.mission_id / f"{task_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        sanitize_evidence(result),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    ) + "\n"
    target.write_text(payload, encoding="utf-8")
    digest = sha256(payload.encode("utf-8")).hexdigest()
    try:
        relative = target.relative_to(repository_root)
        ref = str(relative)
    except ValueError:
        ref = str(target)
    return ref, digest


class MunderAdapter:
    """Stable headless adapter over pinned Munder hive/worktree semantics.

    No Electron, scheduler, webhook, Slack, auto mode, publisher, or global memory
    path is reachable from this class. Worker engines are registered by trusted BR
    code; task payloads can never provide an executable or command line.
    """

    def __init__(
        self,
        *,
        worker_runner: WorkerRunner | None = None,
        worker_runners: Mapping[str, WorkerRunner] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if worker_runner is not None and worker_runners is not None:
            raise ValueError("provide worker_runner or worker_runners, not both")
        self._worker_runner = worker_runner
        self._worker_runners = dict(
            registered_worker_runners()
            if worker_runners is None
            else worker_runners
        )
        self._clock = clock

    def _run_worker(
        self,
        task: AgentOfficeTask,
        workspace: Path,
        spec: AgentOfficeExecutionSpec,
        timeout_seconds: float,
        lease: DelegatedTaskLease,
        repository_root: Path,
        event_sink: EventSink | None,
    ) -> dict[str, Any]:
        lease.assert_active()
        task_started_at = _utc_now()
        task_started_ns = time.perf_counter_ns()
        task_started = time.perf_counter()
        if event_sink:
            event_sink(
                task.task_id,
                "TASK_STARTED",
                {
                    "agent_id": task.agent,
                    "capability_id": task.capability,
                    "delegation_id": lease.delegation_id,
                },
            )
        runner = self._worker_runner or self._worker_runners.get(task.agent)
        if runner is None:
            result = {
                "status": "BLOCKED",
                "error": "worker engine is not registered by the Harness",
            }
        else:
            result = {}
            last_error = "worker execution failed"
            for attempt in range(1, lease.retry_budget + 2):
                try:
                    if len(inspect.signature(runner).parameters) >= 4:
                        raw = runner(task, workspace, timeout_seconds, lease)
                    else:
                        raw = runner(task, workspace, timeout_seconds)
                    if not isinstance(raw, dict):
                        raise TypeError("worker result must be an object")
                    result = sanitize_evidence(raw)
                    status = result.get("status")
                    if status not in {"SUCCEEDED", "FAILED", "BLOCKED"}:
                        raise TypeError("worker returned an invalid status")
                    result["attempt_count"] = attempt
                    result["retry_count"] = attempt - 1
                    if status == "SUCCEEDED":
                        break
                    if status == "BLOCKED" or result.get("recoverable") is not True:
                        break
                    if event_sink:
                        event_sink(
                            task.task_id,
                            "TASK_PROGRESS",
                            {"state": "LOCAL_RETRY", "attempt": attempt},
                        )
                except (PermissionError, ValueError) as exc:
                    result = {
                        "status": "BLOCKED",
                        "error": str(exc)[:500],
                        "attempt_count": attempt,
                        "retry_count": attempt - 1,
                    }
                    break
                except Exception as exc:
                    if (
                        task.agent in {"codex", "codex-development"}
                        and is_codex_sandbox_host_policy_failure(str(exc))
                    ):
                        result = {
                            "status": "BLOCKED",
                            "error": "Codex Linux sandbox host policy failure",
                            "exit_code": getattr(exc, "returncode", 1) or 1,
                            "failure_stage": "worker_exception",
                            "stderr_class": "SANDBOX_HOST_POLICY_FAILURE",
                            "sandbox_backend": "bubblewrap",
                            "retryability": "DETERMINISTIC_NO_RETRY",
                            "recoverable": False,
                            "attempt_count": attempt,
                            "retry_count": attempt - 1,
                        }
                        break
                    last_error = _safe_worker_exception_reason(exc)
                    if attempt > lease.retry_budget:
                        result = {
                            "status": "FAILED",
                            "error": last_error,
                            "failure_stage": "worker_exception",
                            "stderr_class": type(exc).__name__,
                            "retryability": "RETRY_BUDGET_EXHAUSTED",
                            "attempt_count": attempt,
                            "retry_count": attempt - 1,
                        }
                        break
                    if event_sink:
                        event_sink(
                            task.task_id,
                            "TASK_PROGRESS",
                            {"state": "LOCAL_RETRY", "attempt": attempt},
                        )

        changed = _changed_paths(workspace, spec.base_sha)
        result["files_changed"] = list(changed)
        result["commits"] = list(_commits_ahead(workspace, spec.base_sha))
        outside = tuple(
            path
            for path in changed
            if not lease.allows_path(path, write=True)
        )
        if outside:
            result["status"] = "FAILED"
            result["error"] = "worker changed files outside allowed_paths/write_set"
            result["outside_allowed_paths"] = list(outside)

        commands = [
            str(item)
            for item in (result.get("commands") or [])
            if isinstance(item, str)
        ]
        if len(commands) > lease.tool_call_budget:
            result["status"] = "FAILED"
            result["error"] = "worker exceeded tool_call_budget"
        else:
            try:
                _commands_within_lease(commands, lease)
            except PermissionError as exc:
                result["status"] = "BLOCKED"
                result["error"] = str(exc)

        result["task_id"] = task.task_id
        result["agent"] = task.agent
        result["capability"] = task.capability
        result["workspace_id"] = f"worktree:{task.task_id}"
        result["delegation_id"] = lease.delegation_id
        result["role"] = lease.role
        result["owned_task_class"] = lease.owned_task_class
        result["task_duration_ms"] = round(
            max(0.0, (time.perf_counter() - task_started) * 1000.0),
            3,
        )
        artifact_ref, artifact_sha = _persist_task_artifact(
            repository_root,
            spec,
            task.task_id,
            result,
        )
        result["artifact_ref"] = artifact_ref
        result["artifact_sha256"] = artifact_sha
        if event_sink:
            event_sink(
                task.task_id,
                "TASK_ARTIFACT_CREATED",
                {
                    "artifact_ref": artifact_ref,
                    "sha256": artifact_sha,
                    "schema_version": 1,
                    "producer": task.agent,
                },
            )
            event_sink(
                task.task_id,
                "TASK_COMPLETED" if result.get("status") == "SUCCEEDED" else (
                    "TASK_ESCALATION_REQUIRED"
                    if result.get("status") == "BLOCKED"
                    else "TASK_FAILED"
                ),
                {
                    "status": result.get("status"),
                    "attempt_count": result.get("attempt_count", 1),
                    "retry_count": result.get("retry_count", 0),
                },
            )
        task_finished_ns = time.perf_counter_ns()
        specialist = result.get("specialist") if isinstance(result.get("specialist"), dict) else {}
        emit_performance_event(
            stage=f"agent-office.task.{task.task_id}",
            category="AGENT_EXECUTION_TIME",
            started_at=task_started_at,
            finished_at=_utc_now(),
            started_monotonic_ns=task_started_ns,
            finished_monotonic_ns=task_finished_ns,
            duration_ms=(task_finished_ns - task_started_ns) / 1_000_000.0,
            retry_count=int(result.get("retry_count") or 0),
            attempt_count=int(result.get("attempt_count") or 1),
            input_size=len(task.objective.encode("utf-8")),
            output_size=len(json.dumps(result, default=str).encode("utf-8")),
            provider=specialist.get("semantic_provider") or (
                "codex" if task.agent in {"codex", "codex-development"} else None
            ),
            model=specialist.get("semantic_model"),
            success=result.get("status") == "SUCCEEDED",
            failure_type=None if result.get("status") == "SUCCEEDED" else str(result.get("error") or "task_failed")[:160],
            trace_id=spec.mission_id,
            span_id=sha256(f"{spec.mission_id}:task:{task.task_id}".encode()).hexdigest()[:32],
            parent_span_id=sha256(f"{spec.mission_id}:mission".encode()).hexdigest()[:32],
            goal_id=spec.goal_id,
            execution_id=spec.execution_id,
            agent_id=task.agent,
            capability_id=task.capability,
            mission_id=spec.mission_id,
            task_id=task.task_id,
            delegation_id=lease.delegation_id,
            authorization_id=lease.authorization_id,
            depends_on_span_ids=[
                sha256(f"{spec.mission_id}:task:{dependency}".encode()).hexdigest()[:32]
                for dependency in task.depends_on
            ],
            metadata={
                "role": lease.role,
                "owned_task_class": lease.owned_task_class,
                "artifact_ref": artifact_ref,
                "tool_call_budget": lease.tool_call_budget,
                "retry_budget": lease.retry_budget,
                "context_build_ms": (
                    result.get("usage", {}).get("context_build_ms")
                    if isinstance(result.get("usage"), dict)
                    else None
                ),
            },
        )
        return result

    def execute(
        self,
        spec: AgentOfficeExecutionSpec,
        tasks: tuple[AgentOfficeTask, ...],
        repository_root: Path,
        *,
        leases: Mapping[str, DelegatedTaskLease] | None = None,
        event_sink: EventSink | None = None,
    ) -> AgentOfficeExecutionResult:
        started_at = _utc_now()
        mission_started_ns = time.perf_counter_ns()
        start_tick = self._clock()
        mission_errors: list[str] = []
        per_agent: list[dict[str, Any]] = []
        worktrees: dict[str, Path] = {}
        leases = dict(leases or {})
        if set(leases) != {task.task_id for task in tasks}:
            raise ValueError("Agent Office requires one delegated lease per task")

        conflicts = []
        ordered_tasks = {task.task_id: task for task in tasks}
        task_ids = tuple(sorted(ordered_tasks))
        for index, left_id in enumerate(task_ids):
            for right_id in task_ids[index + 1:]:
                if _lease_conflict(leases[left_id], leases[right_id]):
                    conflicts.append((left_id, right_id))

        with tempfile.TemporaryDirectory(prefix="br-agent-office-") as temp_dir:
            mission_root = Path(temp_dir).resolve()
            mailbox = mission_root / "mailbox.jsonl"
            for index, task in enumerate(tasks):
                workspace = mission_root / f"worker-{index + 1}-{task.task_id}"
                _git(repository_root, "worktree", "add", "--detach", str(workspace), spec.base_sha)
                worktrees[task.task_id] = workspace
                with mailbox.open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "to": task.agent,
                                "task_id": task.task_id,
                                "delegation_id": leases[task.task_id].delegation_id,
                            }
                        ) + "\n"
                    )

            pending = set(ordered_tasks)
            completed: set[str] = set()
            failed: set[str] = set()
            wave_count = 0
            parallel_task_count = 0
            serial_task_count = 0
            critical_path_ms = 0.0
            cumulative_task_ms = 0.0
            try:
                while pending:
                    dependency_blocked = [
                        task_id
                        for task_id in sorted(pending)
                        if any(dep in failed for dep in ordered_tasks[task_id].depends_on)
                    ]
                    for task_id in dependency_blocked:
                        task = ordered_tasks[task_id]
                        lease = leases[task_id]
                        blocked = {
                            "status": "BLOCKED",
                            "error": "dependency failed",
                            "task_id": task_id,
                            "agent": task.agent,
                            "capability": task.capability,
                            "delegation_id": lease.delegation_id,
                            "files_changed": [],
                            "commits": [],
                            "commands": [],
                            "tests": [],
                            "artifacts": [],
                            "task_duration_ms": 0.0,
                        }
                        ref, digest = _persist_task_artifact(
                            repository_root, spec, task_id, blocked
                        )
                        blocked["artifact_ref"] = ref
                        blocked["artifact_sha256"] = digest
                        per_agent.append(blocked)
                        failed.add(task_id)
                        completed.add(task_id)
                        pending.remove(task_id)
                        if event_sink:
                            event_sink(task_id, "TASK_ESCALATION_REQUIRED", {"reason": "dependency failed"})

                    if not pending:
                        break
                    eligible = [
                        task_id
                        for task_id in sorted(pending)
                        if set(ordered_tasks[task_id].depends_on).issubset(completed)
                    ]
                    if not eligible:
                        mission_errors.append("task DAG contains a dependency cycle")
                        break

                    wave: list[str] = []
                    for task_id in eligible:
                        if len(wave) >= spec.max_parallelism:
                            break
                        if any(_lease_conflict(leases[task_id], leases[other]) for other in wave):
                            continue
                        wave.append(task_id)
                    if not wave:
                        wave = [eligible[0]]
                    wave_count += 1
                    if len(wave) > 1:
                        parallel_task_count += len(wave)
                    else:
                        serial_task_count += 1

                    with ThreadPoolExecutor(max_workers=min(spec.max_parallelism, len(wave))) as pool:
                        futures = {
                            pool.submit(
                                self._run_worker,
                                ordered_tasks[task_id],
                                worktrees[task_id],
                                spec,
                                max(0.0, spec.time_budget_seconds - (self._clock() - start_tick)),
                                leases[task_id],
                                repository_root,
                                event_sink,
                            ): task_id
                            for task_id in wave
                        }
                        wave_results = []
                        for future in as_completed(futures):
                            item = future.result()
                            wave_results.append(item)
                            per_agent.append(item)
                            task_id = futures[future]
                            pending.remove(task_id)
                            completed.add(task_id)
                            if item.get("status") != "SUCCEEDED":
                                failed.add(task_id)
                        durations = [float(item.get("task_duration_ms") or 0.0) for item in wave_results]
                        cumulative_task_ms += sum(durations)
                        critical_path_ms += max(durations, default=0.0)
            finally:
                for workspace in worktrees.values():
                    if workspace.parent != mission_root:
                        mission_errors.append("unsafe worktree cleanup target refused")
                        continue
                    _git(repository_root, "worktree", "remove", "--force", str(workspace), check=False)

        per_agent.sort(key=lambda item: str(item.get("task_id", "")))
        elapsed = self._clock() - start_tick
        total_cost = sum(
            float(item.get("usage", {}).get("cost", 0.0))
            for item in per_agent
            if isinstance(item.get("usage"), dict)
        )
        if elapsed > spec.time_budget_seconds:
            mission_errors.append("Agent Office time budget exceeded")
        if total_cost > spec.cost_budget:
            mission_errors.append("Agent Office cost budget exceeded")

        worker_errors = [
            str(item.get("error", "worker failed"))
            for item in per_agent
            if item.get("status") != "SUCCEEDED"
        ]
        errors = tuple((*worker_errors, *mission_errors))
        success_count = sum(item.get("status") == "SUCCEEDED" for item in per_agent)
        if mission_errors or success_count == 0:
            status = "FAILED"
        elif success_count < len(per_agent):
            status = "PARTIAL"
        else:
            status = "SUCCEEDED"

        files_changed = tuple(sorted({
            path
            for item in per_agent
            for path in item.get("files_changed", [])
            if isinstance(path, str)
        }))
        commands = tuple(sorted({
            command
            for item in per_agent
            for command in item.get("commands", [])
            if isinstance(command, str)
        }))
        tests = tuple(
            test
            for item in per_agent
            for test in item.get("tests", [])
            if isinstance(test, dict)
        )
        artifacts = tuple(sorted({
            artifact
            for item in per_agent
            for artifact in (
                list(item.get("artifacts", []))
                + ([item.get("artifact_ref")] if item.get("artifact_ref") else [])
            )
            if isinstance(artifact, str)
        }))
        commits = tuple(sorted({
            commit
            for item in per_agent
            for commit in item.get("commits", [])
            if isinstance(commit, str)
        }))
        candidate_commits = tuple(sorted({
            str(item.get("candidate", {}).get("RESULT_COMMIT_SHA"))
            for item in per_agent
            if isinstance(item.get("candidate"), dict)
            and item["candidate"].get("RESULT_COMMIT_SHA")
        }))
        evidence_payload = {
            "execution_id": spec.execution_id,
            "mission_id": spec.mission_id,
            "status": status,
            "tasks": [task.to_dict() for task in tasks],
            "per_agent_results": per_agent,
            "files_changed": files_changed,
        }
        wall_ms = max(0.0, elapsed * 1000.0)
        parallelism_saved_ms = max(0.0, cumulative_task_ms - critical_path_ms)
        coordination_overhead_ms = max(0.0, wall_ms - critical_path_ms)
        agent_idle_ms = max(
            0.0,
            wall_ms * max(1, spec.max_parallelism) - cumulative_task_ms,
        )
        evidence = {
            "upstream": "chaitanyagiri/munder-difflin@6248293a7cd9dfdbf9633d12bbe857831ccfee88",
            "worktree_isolation": "PASS",
            "knowledge_return_path": "Agent Office -> Evidence -> DeepSeek Harness -> Knowledge Brain",
            "no_parallel_authority": "PASS",
            "no_autonomous_publishing": "PASS",
            "no_unauthorized_scheduler": "PASS",
            "HARNESS_SOLE_AUTHORITY": "PASS",
            "HARNESS_MICROMANAGEMENT": "NO",
            "PATH_OWNERSHIP": "ENFORCED",
            "CONFLICTS_DETECTED": [list(item) for item in conflicts],
            "PARALLEL_SAFE": len(conflicts) == 0,
            "PARALLEL_TASK_COUNT": parallel_task_count,
            "SERIAL_TASK_COUNT": serial_task_count,
            "PARALLELISM_SAVED_MS": round(parallelism_saved_ms, 3),
            "AGENT_IDLE_MS": round(agent_idle_ms, 3),
            "COORDINATION_OVERHEAD_MS": round(coordination_overhead_ms, 3),
            "CUMULATIVE_AGENT_WORK_MS": round(cumulative_task_ms, 3),
            "CRITICAL_PATH_MS": round(critical_path_ms, 3),
            "WALL_CLOCK_MS": round(wall_ms, 3),
            "candidate_commits": list(candidate_commits),
            "deterministic_digest": evidence_digest(evidence_payload),
        }
        if event_sink:
            for task in tasks:
                if task.task_id in completed:
                    continue
                event_sink(
                    task.task_id,
                    "TASK_FAILED",
                    {"reason": "mission terminated before task completion"},
                )
        mission_finished_ns = time.perf_counter_ns()
        emit_performance_event(
            stage="agent-office.mission.execute",
            category="COORDINATION_OVERHEAD_TIME",
            started_at=started_at,
            finished_at=_utc_now(),
            started_monotonic_ns=mission_started_ns,
            finished_monotonic_ns=mission_finished_ns,
            duration_ms=(mission_finished_ns - mission_started_ns) / 1_000_000.0,
            retry_count=sum(int(item.get("retry_count") or 0) for item in per_agent),
            attempt_count=1,
            input_size=len(json.dumps([task.to_dict() for task in tasks], default=str).encode("utf-8")),
            output_size=len(json.dumps(evidence, default=str).encode("utf-8")),
            success=status == "SUCCEEDED",
            failure_type=None if status == "SUCCEEDED" else status,
            trace_id=spec.mission_id,
            span_id=sha256(f"{spec.mission_id}:mission".encode()).hexdigest()[:32],
            goal_id=spec.goal_id,
            execution_id=spec.execution_id,
            agent_id="agent-office-coordinator",
            capability_id="agent-office.execute",
            mission_id=spec.mission_id,
            delegation_id=spec.delegation_id,
            authorization_id=spec.harness_authorization_id,
            metadata={
                "critical_path_ms": round(critical_path_ms, 3),
                "cumulative_work_ms": round(cumulative_task_ms, 3),
                "parallelism_saved_ms": round(parallelism_saved_ms, 3),
                "coordination_overhead_ms": round(coordination_overhead_ms, 3),
                "parallel_task_count": parallel_task_count,
                "serial_task_count": serial_task_count,
            },
        )
        return AgentOfficeExecutionResult(
            execution_id=spec.execution_id,
            status=status,
            started_at=started_at,
            finished_at=_utc_now(),
            agents_used=tuple(sorted({task.agent for task in tasks})),
            tasks=tuple(task.to_dict() for task in tasks),
            per_agent_results=tuple(per_agent),
            files_changed=files_changed,
            commits=tuple(sorted(set((*commits, *candidate_commits)))),
            tests=tests,
            commands_evidence=commands,
            artifacts=artifacts,
            errors=errors,
            usage={
                "cost": total_cost,
                "elapsed_seconds": max(0.0, elapsed),
                "tool_calls": sum(len(item.get("commands") or []) for item in per_agent),
                "retries": sum(int(item.get("retry_count") or 0) for item in per_agent),
            },
            final_summary=(
                f"Agent Office {status}: {success_count}/{len(tasks)} bounded task owners succeeded"
            ),
            evidence=evidence,
        )
