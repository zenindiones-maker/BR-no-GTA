from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from app.database.agent_execution_lease_repository import (
    append_task_event,
    persist_lease,
    update_lease_status,
)

from app.services.agent_office.contracts import (
    AgentOfficeExecutionResult,
    AgentOfficeExecutionSpec,
    AgentOfficeTask,
)
from app.services.agent_office.delegation import DelegatedTaskLease, MANDATORY_FORBIDDEN_ACTIONS
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

    @staticmethod
    def _build_task_lease(
        spec: AgentOfficeExecutionSpec,
        task: AgentOfficeTask,
    ) -> DelegatedTaskLease:
        task_allowed_paths = task.allowed_paths or spec.allowed_paths
        task_allowed_tools = task.allowed_tools or spec.allowed_tools
        task_allowed_actions = task.allowed_actions or (task.action,)

        def path_within(path: str, scope: tuple[str, ...]) -> bool:
            normalized = path.replace("\\", "/").strip("/")
            return any(
                normalized == allowed.replace("\\", "/").strip("/")
                or normalized.startswith(
                    f"{allowed.replace('\\\\', '/').strip('/')}/"
                )
                for allowed in scope
                if allowed.strip("/")
            )

        mission_union = tuple(dict.fromkeys(
            (*spec.mission_read_scope, *spec.mission_write_scope)
        ))
        out_of_scope_allowed = tuple(
            path for path in task.allowed_paths
            if not path_within(path, mission_union)
        )
        out_of_scope_read = tuple(
            path for path in task.read_set
            if not path_within(path, spec.mission_read_scope)
        )
        out_of_scope_write = tuple(
            path for path in task.write_set
            if not path_within(path, spec.mission_write_scope)
        )

        if out_of_scope_allowed or out_of_scope_read or out_of_scope_write:
            evidence = {
                "MISSION_PATH_SCOPE": {
                    "read": list(spec.mission_read_scope),
                    "write": list(spec.mission_write_scope),
                },
                "TASK_ID": task.task_id,
                "TASK_CAPABILITY": task.capability,
                "TASK_READ_SET": list(task.read_set),
                "TASK_WRITE_SET": list(task.write_set),
                "OUT_OF_SCOPE_READ_PATHS": list(out_of_scope_read),
                "OUT_OF_SCOPE_WRITE_PATHS": list(out_of_scope_write),
                "OUT_OF_SCOPE_ALLOWED_PATHS": list(out_of_scope_allowed),
            }
            for key, value in evidence.items():
                print(f"{key}={json.dumps(value, sort_keys=True)}", flush=True)
            raise PermissionError(
                "REQUEST_SCOPE_EXPANSION: delegated task exceeds Harness mission path scope"
            )
        if task.allowed_tools and any(tool not in spec.allowed_tools for tool in task.allowed_tools):
            raise PermissionError("task allowed_tools exceed mission tool scope")
        if any(action not in spec.allowed_actions for action in task_allowed_actions):
            raise PermissionError("task action exceeds mission delegated actions")
        forbidden = tuple(
            sorted(
                set(spec.forbidden_actions)
                | set(task.forbidden_actions)
                | set(MANDATORY_FORBIDDEN_ACTIONS)
            )
        )
        task_time = task.time_budget_seconds or spec.time_budget_seconds
        task_cost = spec.cost_budget if task.cost_budget is None else task.cost_budget
        delegation_id = f"{spec.delegation_id}:{task.task_id}"
        return DelegatedTaskLease.from_mapping(
            {
                "mission_id": spec.mission_id,
                "task_id": task.task_id,
                "goal_id": spec.goal_id,
                "harness_decision_id": spec.brain_decision_id,
                "authorization_id": spec.harness_authorization_id,
                "delegation_id": delegation_id,
                "agent_id": task.agent,
                "capability_ids": [task.capability],
                "base_sha": spec.base_sha,
                "allowed_paths": list(task_allowed_paths),
                "allowed_tools": list(task_allowed_tools),
                "allowed_actions": list(task_allowed_actions),
                "forbidden_actions": list(forbidden),
                "input_artifact_refs": list(task.input_artifact_refs or spec.input_artifact_refs),
                "expected_outputs": list(task.expected_outputs or spec.expected_outputs),
                "acceptance_criteria": list(task.acceptance_criteria or spec.acceptance_criteria),
                "evidence_requirements": list(task.evidence_requirements or spec.evidence_requirements),
                "time_budget_seconds": min(task_time, spec.time_budget_seconds),
                "cost_budget": min(float(task_cost), float(spec.cost_budget)),
                "tool_call_budget": min(task.tool_call_budget, spec.tool_call_budget),
                "retry_budget": min(task.retry_budget, spec.retry_budget),
                "max_parallelism": spec.max_parallelism,
                "expires_at": spec.expires_at,
                "escalation_conditions": list(spec.escalation_conditions),
                "owned_task_class": task.owned_task_class,
                "role": task.role,
                "read_set": list(task.read_set),
                "write_set": list(task.write_set),
                "parent_task_id": task.parent_task_id,
            }
        )

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
        leases = {
            task.task_id: self._build_task_lease(spec, task)
            for task in task_tuple
        }
        for lease in leases.values():
            lease.assert_active()
            persist_lease(lease)
            append_task_event(
                mission_id=lease.mission_id,
                task_id=lease.task_id,
                delegation_id=lease.delegation_id,
                event_type="TASK_CREATED",
                payload={
                    "agent_id": lease.agent_id,
                    "capability_ids": list(lease.capability_ids),
                    "base_sha": lease.base_sha,
                    "write_set": list(lease.write_set),
                },
            )

        def event_sink(task_id: str, event_type: str, payload: dict) -> None:
            lease = leases[task_id]
            append_task_event(
                mission_id=lease.mission_id,
                task_id=task_id,
                delegation_id=lease.delegation_id,
                event_type=event_type,
                payload=payload,
            )

        result = self.adapter.execute(
            spec,
            task_tuple,
            self.repository_root,
            leases=leases,
            event_sink=event_sink,
        )
        per_task = {str(item.get("task_id")): item for item in result.per_agent_results}
        for task_id, lease in leases.items():
            task_result = per_task.get(task_id, {})
            succeeded = task_result.get("status") == "SUCCEEDED"
            update_lease_status(
                lease.delegation_id,
                status=(
                    "COMPLETED"
                    if succeeded
                    else (
                        "ESCALATION_REQUIRED"
                        if task_result.get("status") == "BLOCKED"
                        else "FAILED"
                    )
                ),
                result_ref=task_result.get("artifact_ref"),
                result_hash=task_result.get("artifact_sha256"),
                error=None if succeeded else str(task_result.get("error") or "task failed")[:1200],
            )
        return result
