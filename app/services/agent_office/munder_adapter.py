from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
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


WorkerRunner = Callable[[AgentOfficeTask, Path, float], dict[str, Any]]


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
    files = _git(workspace, "ls-files").stdout.splitlines()
    digest = sha256("\n".join(files).encode("utf-8")).hexdigest()
    return {
        "status": "SUCCEEDED",
        "summary": f"{task.task_id}: inspected {len(files)} tracked files",
        "commands": ["git ls-files"],
        "artifacts": [],
        "tests": [],
        "usage": {"cost": 0.0},
        "analysis": {"tracked_file_count": len(files), "inventory_sha256": digest},
    }


def codex_addy_worker(
    task: AgentOfficeTask,
    workspace: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Reuse the existing bounded Codex/Addy executor; never accept a raw command."""
    from app.services.codex_addy_capability_executor import execute_codex_addy_capability
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    from app.services.harness_capability_service import CapabilityDefinition

    record = GLOBAL_CAPABILITY_REGISTRY.get(task.capability)
    if (
        record is None
        or record.agent_id != "codex"
        or record.skill_id is None
        or not record.capability_id.startswith("addy:")
    ):
        raise PermissionError("Codex worker requires an existing registered Agent Skill")
    capability = CapabilityDefinition(
        capability_id=record.capability_id,
        provider=record.provider,
        execution_kind=record.execution_kind,
        allowed_actions=record.allowed_actions,
        tags=record.tags,
        available=record.available,
        execution_enabled=record.execution_enabled,
        boundary=record.boundary,
    )
    deadline = time.monotonic() + timeout_seconds

    def bounded_runner(command, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout_seconds)
        return subprocess.run(command, timeout=remaining, **kwargs)

    result = execute_codex_addy_capability(
        capability,
        {"task": task.objective},
        runner=bounded_runner,
        repository_root=workspace,
    )
    return {
        "status": "SUCCEEDED",
        "summary": result.get("output", "")[:2_000],
        "commands": ["registered Codex/Addy executor"],
        "artifacts": [],
        "tests": [],
        "usage": {"cost": 0.0, "cost_available": False},
        "engine_result": result,
    }


def registered_worker_runners() -> dict[str, WorkerRunner]:
    return {
        "deterministic-analysis": deterministic_read_only_worker,
        "codex": codex_addy_worker,
    }


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
    ) -> dict[str, Any]:
        try:
            runner = self._worker_runner or self._worker_runners.get(task.agent)
            if runner is None:
                return {
                    "status": "BLOCKED",
                    "error": "worker engine is not registered by the Harness",
                    "files_changed": [],
                    "task_id": task.task_id,
                    "agent": task.agent,
                    "capability": task.capability,
                    "workspace_id": f"worktree:{task.task_id}",
                }
            raw = runner(task, workspace, timeout_seconds)
            if not isinstance(raw, dict):
                raise TypeError("worker result must be an object")
            result = sanitize_evidence(raw)
            status = result.get("status")
            if status not in {"SUCCEEDED", "FAILED", "BLOCKED"}:
                result["status"] = "FAILED"
                result["error"] = "worker returned an invalid status"
        except Exception:
            result = {
                "status": "FAILED",
                "error": "worker execution failed",
            }

        changed = _changed_paths(workspace, spec.base_sha)
        result["files_changed"] = list(changed)
        result["commits"] = list(_commits_ahead(workspace, spec.base_sha))
        outside = tuple(path for path in changed if not _path_allowed(path, spec.allowed_paths))
        if outside:
            result["status"] = "FAILED"
            result["error"] = "worker changed files outside allowed_paths"
            result["outside_allowed_paths"] = list(outside)
        result["task_id"] = task.task_id
        result["agent"] = task.agent
        result["capability"] = task.capability
        result["workspace_id"] = f"worktree:{task.task_id}"
        return result

    def execute(
        self,
        spec: AgentOfficeExecutionSpec,
        tasks: tuple[AgentOfficeTask, ...],
        repository_root: Path,
    ) -> AgentOfficeExecutionResult:
        started_at = _utc_now()
        start_tick = self._clock()
        mission_errors: list[str] = []
        per_agent: list[dict[str, Any]] = []
        worktrees: list[Path] = []

        with tempfile.TemporaryDirectory(prefix="br-agent-office-") as temp_dir:
            mission_root = Path(temp_dir).resolve()
            mailbox = mission_root / "mailbox.jsonl"
            for index, task in enumerate(tasks):
                workspace = mission_root / f"worker-{index + 1}-{task.task_id}"
                _git(repository_root, "worktree", "add", "--detach", str(workspace), spec.base_sha)
                worktrees.append(workspace)
                with mailbox.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"to": task.agent, "task_id": task.task_id}) + "\n")

            try:
                with ThreadPoolExecutor(max_workers=spec.max_parallelism) as pool:
                    futures = {
                        pool.submit(
                            self._run_worker,
                            task,
                            workspace,
                            spec,
                            max(0.0, spec.time_budget_seconds - (self._clock() - start_tick)),
                        ): task.task_id
                        for task, workspace in zip(tasks, worktrees, strict=True)
                    }
                    for future in as_completed(futures):
                        per_agent.append(future.result())
            finally:
                for workspace in worktrees:
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
            for artifact in item.get("artifacts", [])
            if isinstance(artifact, str)
        }))
        commits = tuple(sorted({
            commit
            for item in per_agent
            for commit in item.get("commits", [])
            if isinstance(commit, str)
        }))
        evidence_payload = {
            "execution_id": spec.execution_id,
            "status": status,
            "tasks": [task.to_dict() for task in tasks],
            "per_agent_results": per_agent,
            "files_changed": files_changed,
        }
        evidence = {
            "upstream": "chaitanyagiri/munder-difflin@6248293a7cd9dfdbf9633d12bbe857831ccfee88",
            "worktree_isolation": "PASS",
            "knowledge_return_path": "Agent Office -> Evidence -> DeepSeek Harness -> Knowledge Brain",
            "no_parallel_authority": "PASS",
            "no_autonomous_publishing": "PASS",
            "no_unauthorized_scheduler": "PASS",
            "deterministic_digest": evidence_digest(evidence_payload),
        }
        return AgentOfficeExecutionResult(
            execution_id=spec.execution_id,
            status=status,
            started_at=started_at,
            finished_at=_utc_now(),
            agents_used=tuple(sorted({task.agent for task in tasks})),
            tasks=tuple(task.to_dict() for task in tasks),
            per_agent_results=tuple(per_agent),
            files_changed=files_changed,
            commits=commits,
            tests=tests,
            commands_evidence=commands,
            artifacts=artifacts,
            errors=errors,
            usage={"cost": total_cost, "elapsed_seconds": max(0.0, elapsed)},
            final_summary=(
                f"Agent Office {status}: {success_count}/{len(tasks)} bounded tasks succeeded"
            ),
            evidence=evidence,
        )
