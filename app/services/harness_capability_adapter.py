from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import importlib
import inspect
import time
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    authorization_to_context,
    validate_harness_authorization,
)
from app.services.harness_capability_service import execute_capability
from app.services.harness_collaboration_service import RoutedCollaborationTask, TaskEnvelope


_FORBIDDEN_PAYLOAD_FIELDS = {
    "authorization",
    "authorization_id",
    "authorized_action",
    "executor",
    "executor_binding",
    "agent_id",
    "authority",
    "routing_id",
    "publication_authority",
    "policy_override",
}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class CapabilityExecutionResult:
    task_id: str
    capability_id: str
    capability_version: str
    executor_binding: str
    agent_id: str | None
    skill_id: str | None
    routing_id: str
    authorization_id: str
    elapsed_seconds: float
    result: Any
    authority: str = "DEEPSEEK_HARNESS"
    adapter: str = "HARNESS_CAPABILITY_ADAPTER_V1"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result"] = _jsonable(self.result)
        return payload


class CapabilityAdapter:
    """Single Harness-governed adapter from TaskEnvelope to Registry executor."""

    def __init__(self, *, registry=GLOBAL_CAPABILITY_REGISTRY) -> None:
        self.registry = registry

    @staticmethod
    def resolve_binding(binding: str):
        module_name, sep, attr = str(binding or "").rpartition(".")
        if not sep or not module_name or not attr:
            raise PermissionError("Registry executor binding is invalid")
        module = importlib.import_module(module_name)
        executor = getattr(module, attr, None)
        if not callable(executor):
            raise PermissionError("Registry executor binding is not callable")
        actual = (
            f"{getattr(executor, '__module__', '')}."
            f"{getattr(executor, '__name__', '')}"
        )
        if actual != binding:
            raise PermissionError(
                "Resolved executor does not match exact Registry binding"
            )
        return executor

    @staticmethod
    def authorization_subject(executor, task: RoutedCollaborationTask | TaskEnvelope) -> str:
        params = inspect.signature(executor).parameters
        if "execution_context" in params and "authorization" not in params:
            return f"action:{task.action}"
        return f"capability:{task.capability_id}"

    @staticmethod
    def _invoke(*, executor, task, decision, authorization, payload):
        params = inspect.signature(executor).parameters
        if {"authorization", "routing_decision", "payload"}.issubset(params):
            return executor(
                authorization=authorization,
                routing_decision=decision,
                payload=payload,
            )
        if "capability" in params and "payload" in params:
            return execute_capability(
                capability_id=task.capability_id,
                authorization=authorization,
                payload=payload,
                routing_decision=decision,
                executor=executor,
            )
        if "execution_context" in params:
            return executor(authorization_to_context(authorization))
        raise PermissionError(
            "Registry executor signature is not supported by CapabilityAdapter"
        )

    def execute(
        self,
        *,
        authorization,
        task_envelope: RoutedCollaborationTask | TaskEnvelope,
        routing_decision,
        payload: dict[str, Any] | None = None,
        parent_context: dict[str, Any] | None = None,
    ) -> CapabilityExecutionResult:
        task = task_envelope
        record = self.registry.get(task.capability_id)
        if record is None or not record.execution_enabled:
            raise PermissionError("Task capability is not executable in canonical Registry")
        if routing_decision.selected_capability_id != task.capability_id:
            raise PermissionError("Routing decision capability mismatch")
        if routing_decision.selected_executor_binding != record.executor_binding:
            raise PermissionError("Routing decision executor escaped Registry binding")
        if isinstance(task, RoutedCollaborationTask):
            if task.selected_executor_binding != record.executor_binding:
                raise PermissionError("TaskEnvelope executor drifted from Registry")
            if task.capability_version != str(record.version or "1"):
                raise PermissionError("TaskEnvelope capability version drifted")
        executor = self.resolve_binding(str(record.executor_binding or ""))
        auth = validate_harness_authorization(
            authorization,
            expected_action=task.action,
            expected_subject=self.authorization_subject(executor, task),
        )
        body = dict(payload or {})
        if any(str(key).casefold() in _FORBIDDEN_PAYLOAD_FIELDS for key in body):
            raise PermissionError(
                "Capability payload attempted to override authority or routing"
            )
        if parent_context:
            body.setdefault("parent_context", dict(parent_context))
        started = time.perf_counter()
        result = self._invoke(
            executor=executor,
            task=task,
            decision=routing_decision,
            authorization=auth,
            payload=body,
        )
        elapsed = time.perf_counter() - started
        return CapabilityExecutionResult(
            task_id=task.task_id,
            capability_id=record.capability_id,
            capability_version=str(record.version or "1"),
            executor_binding=str(record.executor_binding),
            agent_id=record.agent_id,
            skill_id=record.skill_id,
            routing_id=routing_decision.routing_id,
            authorization_id=auth.authorization_id,
            elapsed_seconds=round(elapsed, 6),
            result=result,
        )
