from __future__ import annotations

import re
from typing import Any, Callable

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)

from .contracts import HERMES_RUNTIME_CAPABILITY_ID, HermesMissionExecutionSpec


_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer\s|token|secret|password|credential|ghp_|github_pat_|sk-)"
)


class HermesHarnessTools:
    """Allowlisted Harness bridge exposed to Hermes workers.

    Hermes can ask for status/capability work and submit evidence. It never
    receives an executor callable, credential, or authorization authority.
    """

    def __init__(
        self,
        *,
        spec: HermesMissionExecutionSpec,
        parent_authorization: HarnessAuthorization | dict[str, Any] | str,
        execution_callback: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.spec = spec
        self.parent_authorization = validate_harness_authorization(
            parent_authorization,
            expected_action="EXECUTION",
            expected_subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        )
        if self.parent_authorization.authorization_id != spec.authorization_id:
            raise PermissionError("Hermes mission authorization_id mismatch")
        if self.parent_authorization.harness_decision_id != spec.harness_decision_id:
            raise PermissionError("Hermes mission decision lineage mismatch")
        self.execution_callback = execution_callback
        self._evidence: list[dict[str, Any]] = []

    def br_harness_status(self, *, task_id: str) -> dict[str, Any]:
        task = self.spec.task(task_id)
        return {
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": self.spec.mission_id,
            "goal_id": self.spec.goal_id,
            "task_id": task.task_id,
            "capability_id": task.capability_id,
            "action": task.action,
            "routing_id": task.routing_id,
            "executor_binding": task.selected_executor_binding,
            "authorization_id": self.spec.authorization_id,
            "base_sha": self.spec.base_sha,
            "forbidden_actions": list(self.spec.forbidden_actions),
        }

    def br_harness_capability_request(
        self,
        *,
        task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task = self.spec.task(task_id)
        record = GLOBAL_CAPABILITY_REGISTRY.get(task.capability_id)
        if record is None:
            raise PermissionError("Hermes requested unknown capability")
        if task.capability_id not in self.spec.allowed_capability_ids:
            raise PermissionError("Hermes requested capability outside mission lease")
        if task.selected_agent_id and task.selected_agent_id not in self.spec.allowed_agent_ids:
            raise PermissionError("Hermes requested agent outside mission lease")
        if task.action not in record.allowed_actions:
            raise PermissionError("Hermes requested unauthorized action")
        if any(str(key).lower() in {"authorization_id", "authorized_action", "executor_binding", "agent_id"} for key in payload):
            raise PermissionError("Hermes payload may not override authority/routing fields")

        decision = route_harness_request(
            HarnessRoutingRequest(
                intent=f"Hermes delegated task {task.task_id}: {task.objective}",
                authorized_action=task.action,
                domain=record.domain,
                goal_id=self.spec.goal_id,
                required_capability_id=task.capability_id,
                fallback_allowed=False,
                provider_required=False,
                learning_required=False,
            )
        )
        if decision.selected_capability_id != task.capability_id:
            raise PermissionError("Harness reroute changed authorized Hermes capability")
        if decision.selected_executor_binding != task.selected_executor_binding:
            raise PermissionError("Harness reroute executor drifted from CollaborationPlan")

        child = issue_harness_authorization(
            authorized_action=task.action,
            subject=f"capability:{task.capability_id}",
            harness_decision_id=self.spec.harness_decision_id,
            execution_id=self.parent_authorization.execution_id,
            lineage={
                "parent_authorization_id": self.parent_authorization.authorization_id,
                "hermes_mission_id": self.spec.mission_id,
                "hermes_task_id": task.task_id,
                "goal_id": self.spec.goal_id,
                "routing_id": decision.routing_id,
                "capability_id": task.capability_id,
                "selected_executor_binding": decision.selected_executor_binding,
                "base_sha": self.spec.base_sha,
            },
        )
        envelope = {
            "status": "AUTHORIZED",
            "authority": "DEEPSEEK_HARNESS",
            "authorization_id": child.authorization_id,
            "routing_id": decision.routing_id,
            "capability_id": task.capability_id,
            "executor_binding": decision.selected_executor_binding,
            "executed": False,
        }
        if self.execution_callback is None:
            return envelope
        result = self.execution_callback(
            task=task,
            payload=dict(payload),
            authorization=child,
            routing_decision=decision,
        )
        return {**envelope, "executed": True, "result": result}

    def br_harness_submit_evidence(
        self,
        *,
        task_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        self.spec.task(task_id)
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError("Hermes evidence must be a non-empty mapping")
        rendered = repr(evidence)
        if _SECRET_PATTERN.search(rendered):
            raise PermissionError("secret/credential-like material is forbidden in Hermes evidence")
        item = {
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "evidence": dict(evidence),
        }
        self._evidence.append(item)
        return {"status": "ACCEPTED", "index": len(self._evidence) - 1}

    def evidence_snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._evidence)
