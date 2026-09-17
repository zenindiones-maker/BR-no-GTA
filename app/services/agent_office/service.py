from __future__ import annotations

import os
from pathlib import Path
import subprocess

from app.services.agent_office.contracts import (
    AgentOfficeExecutionResult,
    AgentOfficeExecutionSpec,
    AgentOfficeTask,
)
from app.services.agent_office.munder_adapter import MunderAdapter
from app.services.harness_authorization_service import validate_harness_authorization


class AgentOfficeService:
    def __init__(self, repository_root: Path, *, adapter: MunderAdapter | None = None) -> None:
        self.repository_root = repository_root.resolve()
        self.adapter = adapter or MunderAdapter()

    def _git_value(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repository_root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _validate_repository_state(self, spec: AgentOfficeExecutionSpec) -> None:
        remote = self._git_value("remote", "get-url", "origin")
        normalized_remote = remote.removesuffix(".git").rstrip("/")
        if not normalized_remote.endswith(f"/{spec.repository}"):
            raise PermissionError("Agent Office repository mismatch")
        actual_sha = self._git_value("rev-parse", "HEAD")
        if actual_sha != spec.base_sha:
            raise PermissionError("Agent Office base SHA mismatch")
        actual_branch = self._git_value("branch", "--show-current")
        workflow_branch = os.getenv("GITHUB_HEAD_REF") or os.getenv("GITHUB_REF_NAME")
        if actual_branch:
            if actual_branch != spec.branch:
                raise PermissionError("Agent Office branch mismatch")
        elif workflow_branch != spec.branch:
            raise PermissionError("Agent Office branch mismatch")

    @staticmethod
    def _validate_tasks(spec: AgentOfficeExecutionSpec, tasks: tuple[AgentOfficeTask, ...]) -> None:
        if not tasks:
            raise ValueError("Agent Office requires at least one task")
        if len(tasks) > 32:
            raise ValueError("Agent Office task count exceeds the bounded limit")
        ids: set[str] = set()
        for task in tasks:
            if task.task_id in ids:
                raise ValueError("Agent Office task_id values must be unique")
            ids.add(task.task_id)
            if task.agent not in spec.allowed_agents:
                raise PermissionError("Agent Office agent is not allowed")
            if task.capability not in spec.allowed_capabilities:
                raise PermissionError("Agent Office capability is not allowed")
            if task.action in spec.forbidden_actions:
                raise PermissionError("Agent Office action is forbidden")

    def execute(
        self,
        spec: AgentOfficeExecutionSpec,
        tasks: list[AgentOfficeTask] | tuple[AgentOfficeTask, ...],
    ) -> AgentOfficeExecutionResult:
        authorization = validate_harness_authorization(
            spec.harness_authorization_id,
            expected_action=spec.authorized_action,
            expected_subject="capability:agent-office.execute",
            expected_execution_id=spec.execution_id,
        )
        if authorization.harness_decision_id != spec.brain_decision_id:
            raise PermissionError("Agent Office brain decision mismatch")
        goal_id = authorization.lineage.get("goal_id")
        if goal_id is not None and goal_id != spec.goal_id:
            raise PermissionError("Agent Office goal lineage mismatch")
        self._validate_repository_state(spec)
        task_tuple = tuple(tasks)
        self._validate_tasks(spec, task_tuple)
        return self.adapter.execute(spec, task_tuple, self.repository_root)
