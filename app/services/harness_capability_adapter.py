from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import inspect
import time
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    authorization_to_context,
    validate_harness_authorization,
)
from app.services.harness_capability_service import (
    CapabilityEvidence,
    execute_capability,
)
from app.services.harness_executor_contract_service import (
    AUTH_ROUTING_PAYLOAD,
    CAPABILITY_PAYLOAD,
    EXECUTION_CONTEXT,
    executor_invocation_contract,
    resolve_registry_executor,
)
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


class CapabilityReturnedFailure(RuntimeError):
    """Fail-closed executor result that completed transport but not capability work."""

    def __init__(
        self,
        capability_id: str,
        status: str,
        safe_reason: str,
        *,
        failure_evidence: dict[str, Any] | None = None,
    ) -> None:
        self.capability_id = str(capability_id)
        self.status = str(status)
        self.safe_reason = str(safe_reason)[:240]
        self.failure_evidence = dict(failure_evidence or {})
        super().__init__(
            f"capability returned non-executed evidence: "
            f"{self.capability_id} status={self.status} reason={self.safe_reason}"
        )


def _failed_capability_reason(value: CapabilityEvidence) -> str:
    result = value.result
    if isinstance(result, dict):
        errors = result.get("errors")
        if isinstance(errors, (list, tuple)):
            for item in errors:
                text = str(item or "").strip()
                if text:
                    return text
        for key in ("error", "failure_mode", "status"):
            text = str(result.get(key) or "").strip()
            if text:
                return text
    return "executor reported failed/inactive CapabilityEvidence"


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
        return resolve_registry_executor(binding)

    @staticmethod
    def authorization_subject(executor, task: RoutedCollaborationTask | TaskEnvelope) -> str:
        contract = executor_invocation_contract(executor)
        if contract == EXECUTION_CONTEXT:
            return f"action:{task.action}"
        return f"capability:{task.capability_id}"

    @staticmethod
    def _invoke(*, executor, task, decision, authorization, payload):
        contract = executor_invocation_contract(executor)
        if contract == AUTH_ROUTING_PAYLOAD:
            return executor(
                authorization=authorization,
                routing_decision=decision,
                payload=payload,
            )
        if contract == CAPABILITY_PAYLOAD:
            return execute_capability(
                capability_id=task.capability_id,
                authorization=authorization,
                payload=payload,
                routing_decision=decision,
                executor=executor,
            )
        if contract == EXECUTION_CONTEXT:
            # The executor contract is keyed by the named execution_context
            # parameter. Passing the authorization context positionally can bind
            # to an unrelated leading parameter (for example ai_provider on the
            # editorial consumer). Preserve caller payload as bounded task
            # context while canonical authorization fields win on collisions.
            execution_context = {
                **dict(payload or {}),
                **authorization_to_context(authorization),
            }
            params = inspect.signature(executor).parameters
            named = {
                name: payload[name]
                for name in params
                if name != "execution_context" and name in payload
            }
            return executor(
                execution_context=execution_context,
                **named,
            )
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
        if record.capability_id == "gta6.research.fresh-cloud":
            # Preserve the canonical fresh-research Registry binding. The
            # TaskEnvelope carries the natural query inside payload, while the
            # canonical executor exposes it as a named argument.
            query = str(body.get("query") or body.get("objective") or "").strip()
            if not query:
                raise ValueError("fresh research TaskEnvelope requires query")
            result = executor(
                query=query,
                authorization=auth,
                routing_decision=routing_decision,
                source_context=(
                    dict(body.get("source_context"))
                    if isinstance(body.get("source_context"), dict)
                    else None
                ),
            )
        elif (
            record.domain == "youtube-department"
            and record.capability_type == "AGENT"
            and body.get("semantic_context") is not None
        ):
            # TUBEGENT keeps the Registry executor as the deterministic
            # capability boundary, while this existing governed wrapper adds
            # Harness-selected semantic reasoning and a live agent receipt.
            from app.services.youtube_department_service import (
                execute_youtube_specialist_via_harness,
            )
            result = execute_youtube_specialist_via_harness(
                authorization=auth,
                routing_decision=routing_decision,
                payload=body,
            )
        else:
            result = self._invoke(
                executor=executor,
                task=task,
                decision=routing_decision,
                authorization=auth,
                payload=body,
            )
        if isinstance(result, CapabilityEvidence) and (
            result.status != "EXECUTED" or result.active is not True
        ):
            raise CapabilityReturnedFailure(
                record.capability_id,
                result.status,
                _failed_capability_reason(result),
                failure_evidence={
                    "capability_id": result.capability_id,
                    "provider": result.provider,
                    "status": result.status,
                    "active": result.active,
                    "result": _jsonable(result.result),
                    "boundary": result.boundary,
                },
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
