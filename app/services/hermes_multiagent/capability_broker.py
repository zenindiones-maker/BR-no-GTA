from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import inspect
import json
from pathlib import Path
import time
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.capability_execution_contract_service import (
    CAN_MUTATE_CANDIDATE,
    CAN_SEMANTIC_REASONING,
    CAN_WRITE_REPOSITORY,
)
from app.services.semantic_tool_loop_service import (
    AGENT_TURN_FINAL_OUTPUT,
    AGENT_TURN_SCHEMA,
    AGENT_TURN_TOOL_REQUEST,
    AgentTurnContractError,
    AgentToolAuthorizationError,
    AgentToolBudgetExceeded,
    AgentToolRequestError,
    MAX_AGENT_CONTEXT_CHARS,
    MAX_AGENT_TURNS,
    MAX_RESUME_AGENT_TURNS,
    MAX_RESUME_SEGMENTS,
    MAX_TOTAL_AGENT_TURNS,
    MAX_PROVIDER_CALLS,
    MAX_TOOL_CALLS,
    TOOL_REQUEST_SCHEMA,
    TOOL_RESULT_SCHEMA,
    build_tool_result_envelope,
    extract_agent_output_text,
    extract_agent_turn,
    extract_exact_json_output,
    extract_tool_request,
    extract_tool_request_candidate,
    provider_call_count,
    tool_request_fingerprint,
    utcnow,
)
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.task_result_envelope_service import (
    DependencyArtifactMissing,
    build_task_result_envelope,
    load_task_result_envelope,
    persist_task_result_envelope,
)
from app.services.task_output_contract_service import (
    TaskOutputContractViolation,
    task_output_contract_descriptor,
    validate_task_output_contract,
)
from app.services.task_input_contract_service import (
    TaskInputContractViolation,
    resolve_task_input_contract,
    scope_task_context,
)
from app.services.harness_internal_recovery_service import (
    HarnessInternalRecoveryState,
)
from app.services.agent_session_service import AgentSessionRuntime
from app.services.task_dependency_precondition_service import (
    TaskDependencyPreconditionFailure,
    validate_task_dependency_preconditions,
)
from app.services.telegram_group_human_surface_service import (
    HUMAN_SURFACE,
    send_harness_message_to_human_group,
)

from app.services.harness_collaboration_service import (
    RoutedCollaborationTask,
    TaskEnvelope,
)
from .contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    HermesMissionExecutionSpec,
    TypedHandoff,
)
from .registry_roster import project_plan_roster
from .profile_factory import HermesProfileFactory


_FORBIDDEN_PAYLOAD_FIELDS = {
    "authorization",
    "authorization_id",
    "authorized_action",
    "executor",
    "executor_binding",
    "agent_id",
    "authority",
    "routing_id",
}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


class DelegatedCapabilityFailure(RuntimeError):
    def __init__(
        self,
        *,
        task_id: str,
        capability_id: str,
        failure_mode: str,
        retry_attempt: int,
        retry_allowed: bool,
        requires_harness_replan: bool,
        failure_evidence: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            f"{failure_mode}: task={task_id} capability={capability_id}"
        )
        self.task_id = task_id
        self.capability_id = capability_id
        self.failure_mode = failure_mode
        self.retry_attempt = retry_attempt
        self.retry_allowed = retry_allowed
        self.requires_harness_replan = requires_harness_replan
        self.failure_evidence = dict(failure_evidence or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "capability_id": self.capability_id,
            "failure_mode": self.failure_mode,
            "retry_attempt": self.retry_attempt,
            "retry_allowed": self.retry_allowed,
            "requires_harness_replan": self.requires_harness_replan,
            "failure_evidence": dict(self.failure_evidence),
            "authority": "DEEPSEEK_HARNESS",
        }


class HermesHarnessCapabilityBroker:
    """Mission-scoped broker between Hermes coordination and Harness execution.

    Hermes receives task ids and evidence references. The broker re-routes every
    capability request, issues a fresh child authorization, invokes only the exact
    Registry binding, persists evidence, and consumes the child authorization.
    """

    def __init__(
        self,
        *,
        spec: HermesMissionExecutionSpec,
        parent_authorization: HarnessAuthorization | dict[str, Any] | str,
        board,
        task_mapping: dict[str, str],
        artifact_dir: str | Path,
        registry=GLOBAL_CAPABILITY_REGISTRY,
    ) -> None:
        self.spec = spec
        self.registry = registry
        self.adapter = CapabilityAdapter(registry=registry)
        self.parent_authorization = validate_harness_authorization(
            parent_authorization,
            expected_action="EXECUTION",
            expected_subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        )
        if self.parent_authorization.authorization_id != spec.authorization_id:
            raise PermissionError("Hermes broker parent authorization mismatch")
        self.board = board
        self.task_mapping = dict(task_mapping)
        if set(self.task_mapping) != set(spec.allowed_task_ids):
            raise PermissionError("Hermes broker task mapping does not match mission lease")
        self.artifact_dir = Path(artifact_dir)
        self.result_dir = self.artifact_dir / "capability-results"
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.roster = project_plan_roster(spec.collaboration_plan, registry=registry)
        self._roster_by_id = {entry.capability_id: entry for entry in self.roster}
        self._task_results: dict[str, list[dict[str, Any]]] = {}
        self._child_tasks: dict[str, RoutedCollaborationTask] = {}
        self._child_parent: dict[str, str] = {}
        self._child_depth: dict[str, int] = {}
        self._handoffs: list[dict[str, Any]] = []
        self._human_requests: list[dict[str, Any]] = []
        self._audit: list[dict[str, Any]] = []
        self.recovery = HarnessInternalRecoveryState(
            mission_id=self.spec.mission_id,
            goal_id=self.spec.goal_id,
            artifact_dir=self.artifact_dir,
        )
        self._load_persisted_results()

    def _load_persisted_results(self) -> None:
        for path in sorted(self.result_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("mission_id") != self.spec.mission_id:
                continue
            task_id = str(payload.get("task_id") or "").strip()
            if not task_id:
                continue
            raw = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            relative = path.relative_to(self.artifact_dir)
            record = {
                **payload,
                "evidence_ref": f"artifact:{relative.as_posix()}",
                "sha256": sha256(raw.encode("utf-8")).hexdigest(),
            }
            self._task_results.setdefault(task_id, []).append(record)

    def _task(self, task_id: str):
        if task_id in self._child_tasks:
            return self._child_tasks[task_id]
        return self.spec.task(task_id)

    def list_allowed_capabilities(self, *, mission_id: str, task_id: str) -> tuple[dict[str, Any], ...]:
        if str(mission_id) != self.spec.mission_id:
            raise PermissionError("Hermes mission id mismatch")
        task = self._task(task_id)
        entry = self._roster_by_id[task.capability_id]
        return (entry.to_dict(),)

    def _route(self, task):
        record = self.registry.get(task.capability_id)
        if record is None or not record.execution_enabled:
            raise PermissionError("Hermes requested non-executable Registry capability")
        decision = route_harness_request(
            HarnessRoutingRequest(
                intent=f"Hermes delegated task {task.task_id}: {task.objective}",
                authorized_action=task.action,
                domain=record.domain,
                task_class=f"hermes:{task.task_id}",
                goal_id=self.spec.goal_id,
                required_capability_id=task.capability_id,
                agent_id=task.selected_agent_id,
                fallback_allowed=False,
                provider_required=False,
                learning_required=True,
            )
        )
        if decision.selected_capability_id != task.capability_id:
            raise PermissionError("Harness reroute changed delegated capability")
        if decision.selected_executor_binding != task.selected_executor_binding:
            raise PermissionError("Harness reroute executor drifted from CollaborationPlan")
        selected = dict(decision.policy_metadata.get("selected_implementation") or {})
        if selected.get("agent_id") != task.selected_agent_id:
            raise PermissionError("Harness reroute agent drifted from CollaborationPlan")
        if selected.get("skill_id") != task.selected_skill_id:
            raise PermissionError("Harness reroute skill drifted from CollaborationPlan")
        return record, decision

    def _issue_child(self, *, task, record, decision, executor) -> HarnessAuthorization:
        return issue_harness_authorization(
            authorized_action=task.action,
            subject=self.adapter.authorization_subject(executor, task),
            harness_decision_id=self.spec.harness_decision_id,
            execution_id=self.parent_authorization.execution_id,
            lineage={
                "parent_authorization_id": self.parent_authorization.authorization_id,
                "hermes_mission_id": self.spec.mission_id,
                "hermes_task_id": task.task_id,
                "goal_id": self.spec.goal_id,
                "routing_id": decision.routing_id,
                "capability_id": task.capability_id,
                "capability_version": task.capability_version,
                "selected_executor_binding": record.executor_binding,
                "agent_id": record.agent_id,
                "skill_id": record.skill_id,
                "runtime": "hermes",
                "base_sha": self.spec.base_sha,
                "idempotency_key": task.idempotency_key,
                "read_scope": list(task.read_scope),
                "write_scope": list(task.write_scope),
                "time_budget_seconds": task.time_budget_seconds,
                "cost_budget": task.cost_budget,
                "context_budget_bytes": task.context_budget_bytes,
                "tool_budget": task.tool_budget,
                "retry_budget": task.retry_budget,
                "expires_at": task.expires_at,
            },
        )

    def _persist_result(
        self,
        *,
        task_id: str,
        capability_id: str,
        agent_id: str | None,
        routing_id: str,
        authorization_id: str,
        elapsed_seconds: float,
        result: Any,
        idempotency_key: str,
        capability_version: str,
        retry_count: int,
        skill_id: str | None = None,
        executor_binding: str = "",
        source_task_ids: tuple[str, ...] = (),
        started_at: str | None = None,
        completed_at: str | None = None,
        status: str = "COMPLETED",
    ) -> dict[str, Any]:
        persist_started = time.perf_counter()
        normalized = _jsonable(result)
        index = len(self._task_results.get(task_id, ())) + 1
        relative = Path("capability-results") / f"{task_id}-{index}.json"
        target = self.artifact_dir / relative
        now = datetime.now(timezone.utc).isoformat()
        task_result = build_task_result_envelope(
            mission_id=self.spec.mission_id,
            task_id=task_id,
            capability_id=capability_id,
            agent_id=agent_id,
            skill_id=skill_id,
            executor_binding=executor_binding,
            status=str(status or ""),
            started_at=started_at or now,
            completed_at=completed_at or now,
            elapsed_ms=float(elapsed_seconds) * 1000.0,
            result=normalized,
            source_task_ids=source_task_ids,
            authorization_id=authorization_id,
        )
        task_result_record = persist_task_result_envelope(
            task_result, artifact_dir=self.artifact_dir, index=index
        )
        payload = {
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "capability_id": capability_id,
            "agent_id": agent_id,
            "runtime": "hermes",
            "routing_id": routing_id,
            "authorization_id": authorization_id,
            "idempotency_key": idempotency_key,
            "capability_version": capability_version,
            "retry_count": int(retry_count),
            "status": str(status or ""),
            "elapsed_seconds": round(elapsed_seconds, 6),
            "cost": 0.0,
            "policy_violations": 0,
            "result": normalized,
            "task_result_ref": task_result_record["task_result_ref"],
            "task_result_sha256": task_result_record["content_sha256"],
            "result_persist_ms": round((time.perf_counter() - persist_started) * 1000.0, 3),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        target.write_text(raw + "\n", encoding="utf-8")
        evidence_ref = f"artifact:{relative.as_posix()}"
        record = {
            **payload,
            "evidence_ref": evidence_ref,
            "sha256": sha256(raw.encode("utf-8")).hexdigest(),
        }
        self._task_results.setdefault(task_id, []).append(record)
        return record

    def _existing_result(self, task) -> dict[str, Any] | None:
        if not task.idempotency_key:
            return None
        for row in reversed(self._task_results.get(task.task_id, ())):
            if (
                row.get("status") == "COMPLETED"
                and row.get("idempotency_key") == task.idempotency_key
                and row.get("capability_id") == task.capability_id
                and str(row.get("capability_version") or "1")
                == str(task.capability_version or "1")
            ):
                validation = validate_task_output_contract(
                    functional_role=task.functional_role,
                    result=row.get("result"),
                )
                if validation.required and not validation.final_output_valid:
                    self._audit.append({
                        "event": "LEGACY_COMPLETION_UNVERIFIED",
                        "authority": "DEEPSEEK_HARNESS",
                        "mission_id": self.spec.mission_id,
                        "task_id": task.task_id,
                        "task_class": task.task_class,
                        "functional_role": task.functional_role,
                        "capability_id": task.capability_id,
                        "output_contract_validation": validation.to_dict(),
                    })
                    continue
                return dict(row)
        return None

    def record_candidate_not_required(
        self,
        *,
        task_id: str,
        reason: str,
        evidence_refs: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        task = self._task(task_id)
        if str(getattr(task, "candidate_requirement", "") or "").upper() != "CONDITIONAL":
            raise PermissionError(
                "candidate NOT_REQUIRED is valid only for a CONDITIONAL TaskEnvelope"
            )
        mutation_intent = bool(tuple(task.write_scope or ())) or str(
            getattr(task, "risk_side_effect_class", "") or ""
        ).strip().upper() in {
            "BOUNDED_MUTATION",
            "MUTATING",
            "MEDIUM",
            "HIGH",
        }
        if not mutation_intent:
            raise PermissionError(
                "candidate NOT_REQUIRED requires a typed mutation-intent TaskEnvelope"
            )
        refs = tuple(dict.fromkeys(
            str(ref).strip() for ref in evidence_refs if str(ref).strip()
        ))
        normalized_reason = " ".join(str(reason or "").split()).strip()[:800]
        if not normalized_reason:
            raise ValueError("candidate NOT_REQUIRED reason is required")
        result = {
            "status": "NOT_REQUIRED",
            "candidate_requirement": "CONDITIONAL",
            "candidate_decision": "NOT_REQUIRED",
            "reason": normalized_reason,
            "evidence_refs": list(refs),
            "candidate": None,
            "builder_self_approval": False,
            "authority": "DEEPSEEK_HARNESS",
        }
        result_row = self._persist_result(
            task_id=task_id,
            capability_id=task.capability_id,
            agent_id=task.selected_agent_id,
            routing_id=task.routing_id,
            authorization_id=self.parent_authorization.authorization_id,
            elapsed_seconds=0.0,
            result=result,
            idempotency_key=task.idempotency_key,
            capability_version=task.capability_version,
            retry_count=0,
            skill_id=task.selected_skill_id,
            executor_binding=task.selected_executor_binding,
            source_task_ids=tuple(task.dependencies),
        )
        self._audit.append({
            "event": "TASK_COMPLETED_NOT_REQUIRED",
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "task_class": task.task_class,
            "capability_id": task.capability_id,
            "routing_id": task.routing_id,
            "authorization_id": self.parent_authorization.authorization_id,
            "idempotency_key": task.idempotency_key,
            "candidate_requirement": "CONDITIONAL",
            "candidate_decision": "NOT_REQUIRED",
            "builder_self_approval": False,
            "evidence_refs": list(refs),
        })
        return {
            "authority": "DEEPSEEK_HARNESS",
            "executed": False,
            "reused": False,
            "not_required": True,
            "capability_id": task.capability_id,
            "agent_id": task.selected_agent_id,
            "routing_id": task.routing_id,
            "authorization_id": self.parent_authorization.authorization_id,
            "executor_binding": task.selected_executor_binding,
            "evidence_ref": result_row["evidence_ref"],
            "result": result,
        }

    @staticmethod
    def _context_chars(value: Any) -> int:
        return len(
            json.dumps(
                _jsonable(value),
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        )

    def _agent_tool_capability_ids(self, task) -> tuple[str, ...]:
        allowed: list[str] = ["artifact.evidence.reuse"]
        role = str(task.functional_role or "").strip().upper()
        if role in {"ROOT_CAUSE", "PROPOSAL"}:
            if self.registry.get("repository.read-scoped") is not None:
                allowed.append("repository.read-scoped")
        for item in tuple(task.allowed_tools or ()):
            candidate = str(item or "").strip()
            if candidate and self.registry.get(candidate) is not None:
                allowed.append(candidate)
        return tuple(dict.fromkeys(allowed))

    @staticmethod
    def _authorized_tool_input_refs(task, context: dict[str, Any]) -> set[str]:
        scoped = context.get("authorized_task_input_refs")
        if isinstance(scoped, (list, tuple, set)):
            refs = {
                str(item).strip()
                for item in scoped
                if str(item).strip()
            }
            for tool_result in context.get("agent_tool_results") or ():
                if not isinstance(tool_result, dict):
                    continue
                refs.update(
                    str(item).strip()
                    for item in (tool_result.get("output_refs") or ())
                    if str(item).strip()
                )
            return refs
        refs = {
            str(item).strip()
            for item in tuple(task.input_refs or ())
            if str(item).strip()
        }
        refs.update(
            str(item).strip()
            for item in (context.get("evidence_refs") or ())
            if str(item).strip()
        )
        for item in context.get("input_artifacts") or ():
            if isinstance(item, dict):
                ref = str(item.get("artifact_ref") or "").strip()
                if ref:
                    refs.add(ref)
        for handoff in context.get("parent_handoffs") or ():
            if not isinstance(handoff, dict):
                continue
            for key in ("task_result_ref", "evidence_ref"):
                ref = str(handoff.get(key) or "").strip()
                if ref:
                    refs.add(ref)
            for key in ("output_artifact_refs", "evidence_refs", "metrics_refs"):
                refs.update(
                    str(item).strip()
                    for item in (handoff.get(key) or ())
                    if str(item).strip()
                )
            result = handoff.get("result")
            if isinstance(result, dict):
                refs.update(
                    str(item).strip()
                    for item in (result.get("artifact_refs") or ())
                    if str(item).strip()
                )
        return refs

    def _prepare_typed_input_context(
        self,
        *,
        task,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        source = dict(context or {})
        explicit_incident_refs = (
            tuple(
                str(item).strip()
                for item in (
                    source.get("input_refs")
                    or source.get("evidence_refs")
                    or ()
                )
                if str(item).strip()
            )
            if str(task.functional_role or "").upper() == "DIAGNOSIS"
            else ()
        )
        validation = resolve_task_input_contract(
            functional_role=task.functional_role,
            task_input_refs=tuple(task.input_refs or ()),
            explicit_incident_refs=explicit_incident_refs,
            parent_handoffs=tuple(source.get("parent_handoffs") or ()),
        )
        if not validation.required:
            return source
        if validation.valid:
            scoped = scope_task_context(source, validation)
            self._audit.append({
                "event": "INPUT_CONTRACT_VALID",
                "authority": "DEEPSEEK_HARNESS",
                "mission_id": self.spec.mission_id,
                "task_id": task.task_id,
                "functional_role": task.functional_role,
                "TASK_INPUT_REF_COUNT": validation.input_ref_count,
                "UNUSED_INPUT_REF_COUNT": 0,
                "OUT_OF_SCOPE_ARTIFACT_ACCESS": 0,
                "task_input_scope_sha256": validation.scope_sha256,
            })
            return scoped

        violation = TaskInputContractViolation(validation)
        classification = self.recovery.observe_failure(
            task=task,
            exc=violation,
            context=source,
            contract_version=str(task.capability_version or "1"),
        )
        decision = self.recovery.select_recovery(classification)
        if (
            not decision.recoverable
            or decision.strategy != "RECOMPUTE_TYPED_INPUT_SCOPE"
        ):
            raise violation
        self.recovery.recovery_started(
            classification=classification,
            decision=decision,
        )
        fresh = self.parent_context(task_id=task.task_id)
        repaired = resolve_task_input_contract(
            functional_role=task.functional_role,
            task_input_refs=tuple(task.input_refs or ()),
            explicit_incident_refs=explicit_incident_refs,
            parent_handoffs=tuple(fresh.get("parent_handoffs") or ()),
        )
        if not repaired.valid:
            raise TaskInputContractViolation(repaired)
        scoped = scope_task_context(fresh, repaired)
        self.recovery.recovery_validated(
            task_id=task.task_id,
            validation="INPUT_CONTRACT_VALID=PASS",
        )
        self.recovery.task_resumed(task.task_id)
        self._audit.append({
            "event": "TASK_INPUT_SCOPE_RECOVERED",
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": self.spec.mission_id,
            "task_id": task.task_id,
            "functional_role": task.functional_role,
            "failure_class": classification.failure_class,
            "recovery_strategy": decision.strategy,
            "INPUT_CONTRACT_VALID": "PASS",
            "TASK_INPUT_REF_COUNT": repaired.input_ref_count,
            "UNUSED_INPUT_REF_COUNT": 0,
            "OUT_OF_SCOPE_ARTIFACT_ACCESS": 0,
            "typed_inputs": dict(repaired.resolved_inputs),
            "task_input_scope_sha256": repaired.scope_sha256,
        })
        return scoped

    def _materialize_tool_input_artifacts(
        self,
        *,
        refs: tuple[str, ...],
        authorized_refs: set[str],
        max_chars: int = 9000,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        remaining = max(0, int(max_chars))
        root = self.artifact_dir.resolve()
        for ref in refs:
            value = str(ref or "").strip()
            if not value:
                continue
            if value not in authorized_refs:
                raise AgentToolAuthorizationError(
                    "TOOL_INPUT_REF_OUTSIDE_TASK_SCOPE:" + value
                )
            if not value.startswith("artifact:"):
                continue
            relative = value.split(":", 1)[1].lstrip("/")
            if not relative:
                raise AgentToolRequestError("TOOL_INPUT_ARTIFACT_REF_EMPTY")
            path = (self.artifact_dir / relative).resolve()
            if path != root and root not in path.parents:
                raise AgentToolAuthorizationError(
                    "TOOL_INPUT_ARTIFACT_PATH_ESCAPE"
                )
            if not path.is_file():
                raise AgentToolRequestError(
                    "TOOL_INPUT_ARTIFACT_NOT_FOUND:" + value
                )
            raw = path.read_bytes()
            decoded = raw.decode("utf-8", errors="replace")
            try:
                content: Any = json.loads(decoded)
                encoding = "json"
            except json.JSONDecodeError:
                content = decoded
                encoding = "text"
            row: dict[str, Any] = {
                "artifact_ref": value,
                "sha256": sha256(raw).hexdigest(),
                "size_bytes": len(raw),
                "encoding": encoding,
            }
            rendered = json.dumps(
                content,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            if remaining > 0 and len(rendered) <= remaining:
                row["content"] = content
                remaining -= len(rendered)
            elif remaining > 0:
                excerpt = rendered[:remaining]
                row["content_excerpt"] = excerpt
                row["content_truncated"] = True
                remaining = 0
            rows.append(row)
        return rows

    @staticmethod
    def _compact_parent_handoffs(context: dict[str, Any]) -> None:
        compacted = []
        for item in context.get("parent_handoffs") or ():
            if not isinstance(item, dict):
                continue
            compacted.append({
                key: item.get(key)
                for key in (
                    "task_id",
                    "functional_role",
                    "input_refs",
                    "capability_id",
                    "agent_id",
                    "skill_id",
                    "task_result_ref",
                    "content_sha256",
                    "result_summary",
                    "output_artifact_refs",
                    "evidence_refs",
                    "metrics_refs",
                    "source_task_ids",
                    "direct_dependency",
                )
                if item.get(key) is not None
            })
        context["parent_handoffs"] = compacted

    def _next_agent_context(
        self,
        *,
        base_context: dict[str, Any],
        tool_results: list[dict[str, Any]],
        previous_output: str,
        agent_turn: int,
        output_validation_feedback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = _jsonable(base_context)
        if not isinstance(context, dict):
            context = {}
        context = dict(context)
        context["agent_turn"] = int(agent_turn)
        context["agent_tool_results"] = list(tool_results)
        if output_validation_feedback:
            context["output_validation_feedback"] = dict(
                output_validation_feedback
            )
        if previous_output:
            context["previous_agent_output"] = previous_output[:2400]
        if self._context_chars(context) <= MAX_AGENT_CONTEXT_CHARS:
            return context

        artifacts = []
        for item in context.get("input_artifacts") or ():
            if isinstance(item, dict):
                artifacts.append({
                    key: item.get(key)
                    for key in ("artifact_ref", "sha256", "size_bytes", "encoding")
                    if item.get(key) is not None
                })
        if artifacts:
            context["input_artifacts"] = artifacts
        self._compact_parent_handoffs(context)
        context.pop("relevant_memory", None)
        context.pop("relevant_human_decisions", None)
        if self._context_chars(context) <= MAX_AGENT_CONTEXT_CHARS:
            return context

        minimal = {
            key: context.get(key)
            for key in (
                "mission_id",
                "task_id",
                "goal_id",
                "task",
                "evidence_refs",
                "allowed_tools",
                "memory_write",
                "dependency_context_sha256",
            )
            if context.get(key) is not None
        }
        direct_handoffs = []
        for item in context.get("parent_handoffs") or ():
            if not isinstance(item, dict) or item.get("direct_dependency") is not True:
                continue
            direct_handoffs.append({
                key: item.get(key)
                for key in (
                    "task_id",
                    "functional_role",
                    "capability_id",
                    "agent_id",
                    "skill_id",
                    "task_result_ref",
                    "content_sha256",
                    "result_summary",
                    "output_artifact_refs",
                    "evidence_refs",
                    "metrics_refs",
                    "source_task_ids",
                    "direct_dependency",
                )
                if item.get(key) is not None
            })
        if direct_handoffs:
            # Direct dependency lineage is an execution contract, not optional
            # prompt context. Keep a refs-only projection even when semantic
            # context is compressed to the hard agent limit.
            minimal["parent_handoffs"] = direct_handoffs
        minimal["agent_turn"] = int(agent_turn)
        minimal["agent_tool_results"] = list(tool_results)
        if output_validation_feedback:
            minimal["output_validation_feedback"] = dict(
                output_validation_feedback
            )
        if previous_output:
            minimal["previous_agent_output"] = previous_output[:1200]
        if self._context_chars(minimal) > MAX_AGENT_CONTEXT_CHARS:
            minimal.pop("previous_agent_output", None)
        if self._context_chars(minimal) > MAX_AGENT_CONTEXT_CHARS:
            raise AgentToolBudgetExceeded("MAX_CONTEXT_CHARS")
        return minimal

    @staticmethod
    def _semantic_runtime_task_text(
        *,
        task,
        base_task_text: str,
        mission_id: str,
        agent_id: str,
        agent_instance_id: str,
        agent_turn: int,
        allowed_tool_capability_ids: tuple[str, ...],
    ) -> str:
        descriptor = task_output_contract_descriptor(task.functional_role)
        runtime_contract = {
            "schema": "SemanticAgentRuntimeContract/v1",
            "mission_id": mission_id,
            "task_id": task.task_id,
            "agent_id": agent_id,
            "agent_instance_id": agent_instance_id,
            "capability_id": task.capability_id,
            "agent_turn": int(agent_turn),
            "final_output_contract": descriptor,
            "tool_request_contract": {
                "schema": TOOL_REQUEST_SCHEMA,
                "allowed_tool_or_capability_ids": list(
                    allowed_tool_capability_ids
                ),
                "operation": "EXECUTE_CAPABILITY",
                "required_fields": [
                    "schema",
                    "request_id",
                    "mission_id",
                    "task_id",
                    "agent_id",
                    "capability_id",
                    "tool_or_capability_id",
                    "operation",
                    "arguments",
                    "input_refs",
                    "reason",
                    "authorization_context",
                ],
                "tool_contracts": {
                    "repository.read-scoped": {
                        "arguments": {
                            "paths": "optional list of repository-relative files",
                            "search_terms": "optional list of exact search terms",
                        },
                        "rule": (
                            "read-only; Harness enforces the task read_scope"
                        ),
                    }
                }
                if "repository.read-scoped"
                in allowed_tool_capability_ids
                else {},
            },
            "agent_turn_contract": {
                "schema": AGENT_TURN_SCHEMA,
                "kinds": [
                    AGENT_TURN_TOOL_REQUEST,
                    AGENT_TURN_FINAL_OUTPUT,
                ],
                "exclusive": True,
            },
            "rules": [
                "Return exactly one AgentTurnEnvelope/v1 JSON object and no surrounding prose.",
                "A turn kind is TOOL_REQUEST or FINAL_OUTPUT, never both.",
                "Never emit ToolResultEnvelope or <tool_result>; only the Harness executor may create tool results.",
                "For TOOL_REQUEST, tool_request.reason is mandatory at the top level of ToolRequestEnvelope/v1.",
                "For FINAL_OUTPUT, final_output must match final_output_contract including its exact schema field.",
                "Never claim that a tool executed unless a real ToolResultEnvelope is present in context.",
                "Do not change mission_id, task_id, agent_id or capability_id.",
            ],
        }
        return (
            str(base_task_text or task.objective).strip()
            + "\n\nHARNESS_RUNTIME_CONTRACT_JSON:\n"
            + json.dumps(
                runtime_contract,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    def _persist_tool_result(
        self,
        *,
        task_id: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> str:
        safe = "".join(
            ch if ch.isalnum() or ch in "._-" else "_"
            for ch in str(request_id)
        )[:96]
        relative = Path("tool-results") / f"{task_id}-{safe}.json"
        target = self.artifact_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ) + "\n",
            encoding="utf-8",
        )
        return f"artifact:{relative.as_posix()}"

    def _execute_agent_tool_request(
        self,
        *,
        task,
        request,
        parent_context: dict[str, Any],
        agent_turn: int,
    ) -> dict[str, Any]:
        target = request.tool_or_capability_id
        if target not in set(self._agent_tool_capability_ids(task)):
            raise AgentToolAuthorizationError(
                "TOOL_NOT_ALLOWLISTED:" + target
            )
        record = self.registry.get(target)
        if record is None or not record.execution_enabled:
            raise AgentToolRequestError("UNKNOWN_TOOL:" + target)
        if task.action not in tuple(record.allowed_actions or ()):
            raise AgentToolAuthorizationError(
                "TOOL_ACTION_NOT_ALLOWED:" + target
            )
        operations = set(getattr(record, "execution_operations", ()) or ())
        if (
            CAN_WRITE_REPOSITORY in operations
            or CAN_MUTATE_CANDIDATE in operations
            or str(getattr(record, "side_effect_class", "") or "").upper()
            not in {"", "READ_ONLY"}
        ):
            raise AgentToolAuthorizationError(
                "READ_ONLY_ROLE_CANNOT_USE_MUTATING_TOOL:" + target
            )
        if request.operation != "EXECUTE_CAPABILITY":
            raise AgentToolRequestError(
                "TOOL_OPERATION_UNSUPPORTED:" + request.operation
            )

        authorized_refs = self._authorized_tool_input_refs(
            task,
            parent_context,
        )
        refs = tuple(dict.fromkeys([
            *request.input_refs,
            *(
                str(item).strip()
                for item in (
                    request.arguments.get("artifact_refs")
                    or request.arguments.get("input_refs")
                    or ()
                )
                if str(item).strip()
            ),
        ]))
        input_artifacts = self._materialize_tool_input_artifacts(
            refs=refs,
            authorized_refs=authorized_refs,
        )

        decision = route_harness_request(
            HarnessRoutingRequest(
                intent=(
                    f"authorized agent tool request for {task.task_id}: "
                    f"{request.reason}"
                ),
                authorized_action=task.action,
                domain=record.domain,
                task_class=f"agent-tool:{task.functional_role.casefold()}",
                goal_id=self.spec.goal_id,
                required_capability_id=target,
                agent_id=record.agent_id,
                fallback_allowed=False,
                provider_required=False,
                learning_required=True,
            )
        )
        if decision.selected_capability_id != target:
            raise AgentToolAuthorizationError(
                "TOOL_ROUTING_CHANGED_CAPABILITY"
            )
        if decision.selected_executor_binding != record.executor_binding:
            raise AgentToolAuthorizationError(
                "TOOL_ROUTING_EXECUTOR_DRIFT"
            )

        tool_task = TaskEnvelope(
            task_id=task.task_id,
            capability_id=target,
            action=task.action,
            objective=request.reason,
            input_refs=refs,
            expected_output=TOOL_RESULT_SCHEMA,
            task_class=f"agent-tool:{task.task_class}",
            functional_role="TOOL",
            mission_policy_class=task.mission_policy_class,
            required_capability_description=request.reason,
            acceptance_criteria=("return observed bounded tool evidence",),
            candidate_requirement="NOT_APPLICABLE",
            required_operations=tuple(
                str(item) for item in operations
            ),
            read_scope=tuple(task.read_scope or ()),
            write_scope=(),
            allowed_tools=(),
            allowed_side_effects=(),
            forbidden_side_effects=tuple(task.forbidden_side_effects or ()),
            time_budget_seconds=max(1, min(int(task.time_budget_seconds), 300)),
            cost_budget=0.0,
            context_budget_bytes=min(
                int(task.context_budget_bytes),
                MAX_AGENT_CONTEXT_CHARS,
            ),
            tool_budget=0,
            retry_budget=0,
            evidence_contract=str(record.evidence_contract or ""),
            review_policy="NONE",
            risk_side_effect_class="READ_ONLY",
            idempotency_key=(
                f"agent-tool:{self.spec.mission_id}:"
                f"{task.task_id}:{request.request_id}"
            ),
            expires_at=task.expires_at,
            human_gate_policy="NONE",
            mission_id=self.spec.mission_id,
            goal_id=self.spec.goal_id,
        )
        executor = self.adapter.resolve_binding(
            str(record.executor_binding or "")
        )
        tool_auth = issue_harness_authorization(
            authorized_action=task.action,
            subject=self.adapter.authorization_subject(
                executor,
                tool_task,
            ),
            harness_decision_id=self.spec.harness_decision_id,
            execution_id=self.parent_authorization.execution_id,
            lineage={
                "parent_authorization_id": (
                    self.parent_authorization.authorization_id
                ),
                "hermes_mission_id": self.spec.mission_id,
                "hermes_task_id": task.task_id,
                "goal_id": self.spec.goal_id,
                "agent_turn": int(agent_turn),
                "request_id": request.request_id,
                "requested_by_agent_id": request.agent_id,
                "requested_by_capability_id": request.capability_id,
                "capability_id": target,
                "routing_id": decision.routing_id,
                "selected_executor_binding": record.executor_binding,
                "risk_side_effect_class": "READ_ONLY",
            },
        )
        payload = dict(request.arguments)
        payload.pop("artifact_refs", None)
        payload.pop("input_refs", None)
        if refs:
            payload["input_artifact_refs"] = list(refs)
        if target == "repository.read-scoped":
            payload["repository_root"] = str(Path.cwd().resolve())
            payload["allowed_paths"] = list(task.read_scope or ())
            payload["max_chars"] = min(
                MAX_TOOL_RESULT_CHARS,
                MAX_AGENT_CONTEXT_CHARS,
            )
        tool_context = dict(parent_context)
        if input_artifacts:
            tool_context["input_artifacts"] = input_artifacts
        payload["context"] = tool_context
        started_at = utcnow()
        try:
            adapted = self.adapter.execute(
                authorization=tool_auth,
                task_envelope=tool_task,
                routing_decision=decision,
                payload=payload,
                parent_context=None,
            )
            result = adapted.result
            status = "EXECUTED"
            error = None
        except Exception as exc:
            result = {
                "error_type": type(exc).__name__,
                "error": str(exc)[:1200],
            }
            status = "FAILED"
            error = dict(result)
        finally:
            consume_harness_authorization(tool_auth)
        finished_at = utcnow()

        envelope = build_tool_result_envelope(
            request=request,
            tool_id=target,
            operation=request.operation,
            authorization_id=tool_auth.authorization_id,
            output_refs=(),
            result_payload=result,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            error=error,
        )
        body = envelope.to_dict()
        artifact_ref = self._persist_tool_result(
            task_id=task.task_id,
            request_id=request.request_id,
            payload=body,
        )
        body["output_refs"] = [artifact_ref]
        self._persist_tool_result(
            task_id=task.task_id,
            request_id=request.request_id,
            payload=body,
        )
        self._audit.append({
            "event": (
                "TOOL_EXECUTED"
                if status == "EXECUTED"
                else "TOOL_FAILED"
            ),
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": self.spec.mission_id,
            "task_id": task.task_id,
            "functional_role": task.functional_role,
            "agent_turn": int(agent_turn),
            "request_id": request.request_id,
            "tool_id": target,
            "operation": request.operation,
            "authorization_id": tool_auth.authorization_id,
            "routing_id": decision.routing_id,
            "status": status,
            "tool_result_ref": artifact_ref,
        })
        if status != "EXECUTED":
            raise AgentToolRequestError(
                "TOOL_EXECUTION_FAILED:" + target
            )
        return body

    def _persist_loop_failure(
        self,
        *,
        task,
        record,
        decision,
        authorization_id: str,
        elapsed: float,
        started_at: str,
        retry_attempt: int,
        status: str,
        result: dict[str, Any],
        failure_mode: str,
    ) -> None:
        result_row = self._persist_result(
            task_id=task.task_id,
            capability_id=task.capability_id,
            agent_id=record.agent_id,
            routing_id=decision.routing_id,
            authorization_id=authorization_id,
            elapsed_seconds=elapsed,
            result=result,
            idempotency_key=task.idempotency_key,
            capability_version=task.capability_version,
            retry_count=retry_attempt,
            skill_id=record.skill_id,
            executor_binding=str(record.executor_binding or ""),
            source_task_ids=tuple(task.dependencies),
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            status=status,
        )
        self._audit.append({
            "event": f"TASK_{status}",
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": self.spec.mission_id,
            "task_id": task.task_id,
            "task_class": task.task_class,
            "functional_role": task.functional_role,
            "capability_id": task.capability_id,
            "routing_id": decision.routing_id,
            "authorization_id": authorization_id,
            "status": status,
            "failure_mode": failure_mode,
            "evidence_ref": result_row["evidence_ref"],
        })

    def execute_delegated_capability(
        self,
        *,
        task_id: str,
        capability_id: str,
        payload: dict[str, Any],
        retry_attempt: int = 0,
        dependency_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = self._task(task_id)
        if capability_id != task.capability_id:
            raise PermissionError(
                "Hermes cannot reroute a task to another capability; "
                "return to DeepSeek Harness for replan"
            )
        if any(str(key).lower() in _FORBIDDEN_PAYLOAD_FIELDS for key in payload):
            raise PermissionError(
                "Hermes payload attempted to override authority or routing"
            )
        if capability_id not in self.spec.allowed_capability_ids:
            raise PermissionError("Hermes capability is outside mission lease")

        existing = self._existing_result(task)
        if existing is not None:
            self._audit.append({
                "event": "TASK_COMPLETED_REUSED",
                "authority": "DEEPSEEK_HARNESS",
                "mission_id": self.spec.mission_id,
                "task_id": task_id,
                "capability_id": capability_id,
                "idempotency_key": task.idempotency_key,
                "evidence_ref": existing["evidence_ref"],
                "DUPLICATE_AGENT_EXECUTION_AVOIDED": "PASS",
            })
            return {
                "authority": "DEEPSEEK_HARNESS",
                "executed": False,
                "reused": True,
                "DUPLICATE_AGENT_EXECUTION_AVOIDED": "PASS",
                "capability_id": capability_id,
                "agent_id": existing.get("agent_id"),
                "routing_id": existing.get("routing_id"),
                "authorization_id": existing.get("authorization_id"),
                "executor_binding": task.selected_executor_binding,
                "evidence_ref": existing["evidence_ref"],
                "result": existing.get("result"),
            }

        if retry_attempt < 0 or retry_attempt > int(task.retry_budget):
            raise PermissionError("retry attempt exceeds TaskEnvelope retry budget")
        if retry_attempt > 0 and not task.supports_retry:
            raise PermissionError("capability does not support retry")

        prepared_context = dependency_context
        if task.dependencies:
            if prepared_context is None:
                prepared_context = self.parent_context(task_id=task_id)
            direct = {
                str(item.get("task_id") or ""): item
                for item in (prepared_context.get("parent_handoffs") or ())
                if item.get("direct_dependency") is True
            }
            for dependency in task.dependencies:
                rows = self._task_results.get(dependency) or []
                if not rows:
                    raise DependencyArtifactMissing(
                        task_id=task_id,
                        dependency_task_id=dependency,
                        resolution_attempts=(f"result-snapshot:{dependency}",),
                    )
                latest = rows[-1]
                supplied = direct.get(dependency)
                expected_ref = str(latest.get("task_result_ref") or latest.get("evidence_ref") or "")
                expected_hash = str(latest.get("task_result_sha256") or latest.get("sha256") or "")
                if supplied is None or str(supplied.get("task_result_ref") or "") != expected_ref or str(supplied.get("content_sha256") or "") != expected_hash:
                    raise PermissionError("prepared dependency context does not match persisted artifact")
            payload = dict(payload)
            payload["context"] = prepared_context
            payload.pop("parent_context", None)

        try:
            precondition = validate_task_dependency_preconditions(
                task=task,
                dependency_context=prepared_context,
                task_lookup=self._task,
            )
        except TaskDependencyPreconditionFailure as exc:
            self._audit.append({
                "event": "TASK_PRECONDITION_FAILED",
                "authority": "DEEPSEEK_HARNESS",
                "mission_id": self.spec.mission_id,
                "task_id": task_id,
                "task_class": task.task_class,
                "capability_id": capability_id,
                "failure_mode": exc.code,
                "dependency_task_id": exc.dependency_task_id,
                "details": dict(exc.details),
                "provider_call_executed": False,
            })
            raise
        self._audit.append({
            "event": "TASK_PRECONDITION_PASSED",
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "capability_id": capability_id,
            "provider_call_executed": False,
            "precondition": precondition,
        })

        prepared_context = self._prepare_typed_input_context(
            task=task,
            context=prepared_context or payload.get("context") or {},
        )
        payload = dict(payload)
        payload["context"] = prepared_context

        record, decision = self._route(task)
        base_payload = dict(payload)
        base_context = dict(
            base_payload.get("context")
            or prepared_context
            or {}
        )
        base_task_text = str(
            base_payload.get("task")
            or task.objective
        ).strip()
        output_contract = task_output_contract_descriptor(
            task.functional_role
        )
        semantic_loop = bool(output_contract.get("required"))
        agent_turn_protocol = bool(
            semantic_loop
            and CAN_SEMANTIC_REASONING in set(
                tuple(getattr(record, "execution_operations", ()) or ())
            )
        )
        max_agent_turns = MAX_AGENT_TURNS if semantic_loop else 1
        max_tool_calls = min(
            MAX_TOOL_CALLS,
            max(0, int(task.tool_budget)),
        )
        allowed_tool_ids = (
            self._agent_tool_capability_ids(task)
            if semantic_loop
            else ()
        )
        mandatory_tool_requirements = (
            ("ROOT_CAUSE_REQUIRES_REAL_TOOL_EVIDENCE",)
            if (
                str(task.functional_role or "").upper() == "ROOT_CAUSE"
                and allowed_tool_ids
            )
            else ()
        )
        session = AgentSessionRuntime(
            artifact_dir=self.artifact_dir,
            mission_id=self.spec.mission_id,
            task_id=task.task_id,
            capability_id=task.capability_id,
            agent_id=str(record.agent_id or capability_id),
            skill_id=record.skill_id,
            functional_role=task.functional_role,
            execution_kind=str(
                getattr(record, "resolved_execution_kind", "")
                or getattr(record, "execution_kind", "")
                or ""
            ),
            allowed_tools=tuple(allowed_tool_ids),
            input_artifact_refs=tuple(dict.fromkeys([
                *(
                    str(item).strip()
                    for item in tuple(task.input_refs or ())
                    if str(item).strip()
                ),
                *(
                    str(item).strip()
                    for item in (base_context.get("evidence_refs") or ())
                    if str(item).strip()
                ),
            ])),
            max_agent_turns=max_agent_turns,
            max_tool_calls=max_tool_calls,
            max_provider_calls=MAX_PROVIDER_CALLS,
            max_context_chars=MAX_AGENT_CONTEXT_CHARS,
            max_wall_clock_seconds=float(task.time_budget_seconds),
            mandatory_tool_requirements=mandatory_tool_requirements,
        )
        reclaimed_pre_provider_turn = (
            session.reclaim_unexecuted_pre_provider_turn()
            if session.restored
            else False
        )
        restored_tool_rows = (
            session.prior_tool_results()
            if session.restored
            else []
        )
        tool_results: list[dict[str, Any]] = [
            dict(item["result"])
            for item in restored_tool_rows
            if isinstance(item.get("result"), dict)
        ]
        tool_result_by_fingerprint: dict[str, dict[str, Any]] = {}
        seen_request_ids: set[str] = set()
        for item in restored_tool_rows:
            request = extract_tool_request(
                item.get("request") or {},
                mission_id=self.spec.mission_id,
                task_id=task.task_id,
                agent_id=str(record.agent_id or ""),
                capability_id=task.capability_id,
            )
            result_row = item.get("result")
            if request is None or not isinstance(result_row, dict):
                continue
            seen_request_ids.add(request.request_id)
            tool_result_by_fingerprint[
                tool_request_fingerprint(request)
            ] = dict(result_row)

        session_recovery = (
            session.provider_recovery_state()
            if session.restored
            else {}
        )
        if session_recovery.get("RECOVERY_STRATEGY"):
            base_context = dict(base_context)
            prior_internal = dict(
                base_context.get("internal_recovery") or {}
            )
            base_context["internal_recovery"] = {
                **prior_internal,
                **{
                    key: value
                    for key, value in session_recovery.items()
                    if value not in (None, "", [], {})
                },
                "ORIGINAL_MISSION_ID": self.spec.mission_id,
                "ORIGINAL_GOAL_ID": self.spec.goal_id,
                "FAILED_TASK_ID": task.task_id,
            }

        restored_turn_index = (
            int(session.state.get("TURN_INDEX") or 0)
            if session.restored
            else 0
        )
        turn_window = session.reserve_turn_window(
            default_max_agent_turns=max_agent_turns,
            max_resume_agent_turns=MAX_RESUME_AGENT_TURNS,
            max_resume_segments=MAX_RESUME_SEGMENTS,
            max_total_agent_turns=MAX_TOTAL_AGENT_TURNS,
        )
        start_agent_turn = int(turn_window["start_turn"])
        end_agent_turn = int(turn_window["end_turn"])
        previous_output = ""
        output_validation_feedback: dict[str, Any] | None = None
        provider_calls = int(
            session_recovery.get("PROVIDER_CALL_COUNT") or 0
        )
        tool_calls = len({
            str(item.get("request_id") or "")
            for item in tool_results
            if str(item.get("request_id") or "")
        })
        if session.restored:
            self._audit.append({
                "event": "AGENT_SESSION_RESTORED",
                "authority": "DEEPSEEK_HARNESS",
                "mission_id": self.spec.mission_id,
                "task_id": task.task_id,
                "capability_id": task.capability_id,
                "agent_id": record.agent_id,
                "agent_instance_id": session.agent_instance_id,
                "checkpoint_ref": session.artifact_ref,
                "restored_turn_index": restored_turn_index,
                "next_turn_index": start_agent_turn,
                "resume_turn_end": end_agent_turn,
                "resume_segment": turn_window.get("resume_segment"),
                "historical_turns": turn_window.get("historical_turns"),
                "AGENT_RESUME_BUDGET_BOUNDED": "PASS",
                "AGENT_RESUME_BUDGET_NOT_RESET_BLINDLY": "PASS",
                "restored_tool_result_count": len(tool_results),
                "PRIOR_TOOL_RESULT_AVAILABLE": (
                    "PASS" if tool_results else "NOT_APPLICABLE"
                ),
                "restored_provider_call_count": provider_calls,
                "TASK_AGENT_SESSION_RESTORED": "PASS",
                "PRE_PROVIDER_TURN_RECLAIMED": (
                    "PASS"
                    if reclaimed_pre_provider_turn
                    else "NOT_APPLICABLE"
                ),
                "SAME_AGENT_AFTER_TOOL_RESULT": "PASS",
                "PRIOR_TOOL_RESULT_CONSUMED": (
                    "PASS" if tool_results else "NOT_APPLICABLE"
                ),
                "FAILED_PROVIDER_ATTEMPTS_PERSISTED": (
                    "PASS"
                    if session_recovery.get(
                        "FAILED_PROVIDER_ATTEMPTS_PERSISTED"
                    )
                    else "NOT_APPLICABLE"
                ),
            })
        task_started_perf = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        last_authorization_id = self.parent_authorization.authorization_id
        last_elapsed = 0.0
        last_result: Any = None

        if start_agent_turn > end_agent_turn:
            raise DelegatedCapabilityFailure(
                task_id=task_id,
                capability_id=capability_id,
                failure_mode="AgentToolBudgetExceeded",
                retry_attempt=retry_attempt,
                retry_allowed=False,
                requires_harness_replan=True,
            )

        for agent_turn in range(start_agent_turn, end_agent_turn + 1):
            elapsed_wall = time.perf_counter() - task_started_perf
            if elapsed_wall > float(task.time_budget_seconds):
                failure_result = {
                    "error": "MAX_TASK_WALL_CLOCK_MS",
                    "agent_loop": {
                        "agent_turns": agent_turn - 1,
                        "tool_calls": tool_calls,
                        "provider_calls": provider_calls,
                    },
                }
                self._persist_loop_failure(
                    task=task,
                    record=record,
                    decision=decision,
                    authorization_id=last_authorization_id,
                    elapsed=elapsed_wall,
                    started_at=started_at,
                    retry_attempt=retry_attempt,
                    status="FAILED_BUDGET",
                    result=failure_result,
                    failure_mode="MAX_TASK_WALL_CLOCK_MS",
                )
                raise DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode="AgentToolBudgetExceeded",
                    retry_attempt=retry_attempt,
                    retry_allowed=False,
                    requires_harness_replan=True,
                )

            turn_payload = dict(base_payload)
            turn_context = self._next_agent_context(
                base_context=base_context,
                tool_results=tool_results,
                previous_output=previous_output,
                agent_turn=agent_turn,
                output_validation_feedback=output_validation_feedback,
            )
            turn_context["agent_session"] = {
                "schema": "AgentSessionProjection/v1",
                "agent_instance_id": session.agent_instance_id,
                "turn_index": agent_turn,
                "checkpoint_ref": session.artifact_ref,
                "tools_available": list(allowed_tool_ids),
                "mandatory_tool_requirements": list(
                    mandatory_tool_requirements
                ),
            }
            turn_payload["context"] = turn_context
            turn_payload["agent_turn"] = agent_turn
            turn_payload["agent_instance_id"] = session.agent_instance_id
            turn_payload["functional_role"] = task.functional_role
            turn_payload["agent_tool_capabilities"] = list(
                allowed_tool_ids
            )
            if agent_turn_protocol:
                turn_payload["agent_turn_schema"] = AGENT_TURN_SCHEMA
            turn_payload["task"] = self._semantic_runtime_task_text(
                task=task,
                base_task_text=base_task_text,
                mission_id=self.spec.mission_id,
                agent_id=str(record.agent_id or ""),
                agent_instance_id=session.agent_instance_id,
                agent_turn=agent_turn,
                allowed_tool_capability_ids=allowed_tool_ids,
            )

            executor = self.adapter.resolve_binding(
                str(record.executor_binding or "")
            )
            child = self._issue_child(
                task=task,
                record=record,
                decision=decision,
                executor=executor,
            )
            last_authorization_id = child.authorization_id
            try:
                adapted = self.adapter.execute(
                    authorization=child,
                    task_envelope=task,
                    routing_decision=decision,
                    payload=turn_payload,
                    parent_context=None,
                )
                result = adapted.result
                last_result = result
                last_elapsed = float(adapted.elapsed_seconds)
                session.begin_turn(agent_turn)
                session.record_provider_result(result)
            except Exception as exc:
                retry_allowed = (
                    bool(task.supports_retry)
                    and retry_attempt < int(task.retry_budget)
                )
                failure_evidence = dict(
                    getattr(exc, "failure_evidence", {}) or {}
                )
                routing_policy_evidence = getattr(exc, "evidence", None)
                if isinstance(routing_policy_evidence, dict):
                    failure_evidence = {
                        **failure_evidence,
                        "routing_policy_error": {
                            "error_type": type(exc).__name__,
                            "message": str(exc)[:1200],
                            "evidence": dict(routing_policy_evidence),
                        },
                    }
                turn_consumed = provider_call_count(failure_evidence) > 0
                if turn_consumed:
                    session.begin_turn(agent_turn)
                session.fail(
                    failure_class=type(exc).__name__,
                    evidence=failure_evidence,
                    turn_consumed=turn_consumed,
                )
                failure = DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode=type(exc).__name__,
                    retry_attempt=retry_attempt,
                    retry_allowed=retry_allowed,
                    requires_harness_replan=not retry_allowed,
                    failure_evidence=failure_evidence,
                )
                self._audit.append({
                    "event": "TASK_FAILED",
                    "authority": "DEEPSEEK_HARNESS",
                    "mission_id": self.spec.mission_id,
                    "task_id": task_id,
                    "task_class": task.task_class,
                    "capability_id": capability_id,
                    "routing_id": decision.routing_id,
                    "authorization_id": child.authorization_id,
                    "parent_authorization_id": self.parent_authorization.authorization_id,
                    "idempotency_key": task.idempotency_key,
                    "retry_count": retry_attempt,
                    "retry_allowed": retry_allowed,
                    "requires_harness_replan": not retry_allowed,
                    "failure_mode": type(exc).__name__,
                    "failure_evidence": failure_evidence,
                    "evidence_refs": [],
                })
                raise failure from exc
            finally:
                consume_harness_authorization(child)

            observed_provider_calls = provider_call_count(result)
            if semantic_loop:
                provider_calls += max(1, observed_provider_calls)
            else:
                provider_calls += observed_provider_calls
            if provider_calls > MAX_PROVIDER_CALLS:
                failure_result = {
                    "provider_result": _jsonable(result),
                    "error": "MAX_PROVIDER_CALLS",
                    "agent_loop": {
                        "agent_turns": agent_turn,
                        "tool_calls": tool_calls,
                        "provider_calls": provider_calls,
                    },
                }
                self._persist_loop_failure(
                    task=task,
                    record=record,
                    decision=decision,
                    authorization_id=last_authorization_id,
                    elapsed=time.perf_counter() - task_started_perf,
                    started_at=started_at,
                    retry_attempt=retry_attempt,
                    status="FAILED_BUDGET",
                    result=failure_result,
                    failure_mode="MAX_PROVIDER_CALLS",
                )
                raise DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode="AgentToolBudgetExceeded",
                    retry_attempt=retry_attempt,
                    retry_allowed=False,
                    requires_harness_replan=True,
                )

            validation_subject = result
            if agent_turn_protocol:
                try:
                    parsed_turn = extract_agent_turn(
                        result,
                        mission_id=self.spec.mission_id,
                        task_id=task.task_id,
                        agent_id=str(record.agent_id or ""),
                        capability_id=task.capability_id,
                    )
                except AgentToolAuthorizationError as exc:
                    self._persist_loop_failure(
                        task=task,
                        record=record,
                        decision=decision,
                        authorization_id=last_authorization_id,
                        elapsed=time.perf_counter() - task_started_perf,
                        started_at=started_at,
                        retry_attempt=retry_attempt,
                        status="FAILED_TOOL",
                        result={
                            "provider_result": _jsonable(result),
                            "agent_turn_error": {
                                "error_type": type(exc).__name__,
                                "error": str(exc)[:1200],
                            },
                        },
                        failure_mode=type(exc).__name__,
                    )
                    raise DelegatedCapabilityFailure(
                        task_id=task_id,
                        capability_id=capability_id,
                        failure_mode=type(exc).__name__,
                        retry_attempt=retry_attempt,
                        retry_allowed=False,
                        requires_harness_replan=True,
                    ) from exc
                except (AgentToolRequestError, AgentTurnContractError) as exc:
                    self._persist_loop_failure(
                        task=task,
                        record=record,
                        decision=decision,
                        authorization_id=last_authorization_id,
                        elapsed=time.perf_counter() - task_started_perf,
                        started_at=started_at,
                        retry_attempt=retry_attempt,
                        status="FAILED_CONTRACT",
                        result={
                            "provider_result": _jsonable(result),
                            "agent_turn_error": {
                                "error_type": type(exc).__name__,
                                "error": str(exc)[:1200],
                            },
                            "FAKE_TOOL_RESULT_ACCEPTED": "NO",
                        },
                        failure_mode=type(exc).__name__,
                    )
                    raise DelegatedCapabilityFailure(
                        task_id=task_id,
                        capability_id=capability_id,
                        failure_mode=type(exc).__name__,
                        retry_attempt=retry_attempt,
                        retry_allowed=False,
                        requires_harness_replan=True,
                    ) from exc

                if parsed_turn.kind == AGENT_TURN_TOOL_REQUEST:
                    validation_subject = {}
                else:
                    validation_subject = dict(
                        parsed_turn.final_output or {}
                    )
                    if (
                        str(task.functional_role or "").upper()
                        == "ROOT_CAUSE"
                        and tool_calls < 1
                        and allowed_tool_ids
                    ):
                        output_validation_feedback = {
                            "schema": "AgentTurnValidationFeedback/v1",
                            "expected_schema": AGENT_TURN_SCHEMA,
                            "errors": [
                                "ROOT_CAUSE_REQUIRES_REAL_TOOL_EVIDENCE"
                            ],
                            "instruction": (
                                "Return a TOOL_REQUEST AgentTurn using an "
                                "allowlisted read-only evidence capability. "
                                "Root cause must be grounded in at least one "
                                "real Harness tool execution before FINAL_OUTPUT."
                            ),
                        }
                        validation_row = self._persist_result(
                            task_id=task_id,
                            capability_id=capability_id,
                            agent_id=record.agent_id,
                            routing_id=decision.routing_id,
                            authorization_id=last_authorization_id,
                            elapsed_seconds=(
                                time.perf_counter() - task_started_perf
                            ),
                            result={
                                "provider_result": _jsonable(result),
                                "output_validation_feedback": (
                                    output_validation_feedback
                                ),
                                "agent_loop": {
                                    "agent_turns": agent_turn,
                                    "tool_calls": tool_calls,
                                    "provider_calls": provider_calls,
                                },
                            },
                            idempotency_key=task.idempotency_key,
                            capability_version=task.capability_version,
                            retry_count=retry_attempt,
                            skill_id=record.skill_id,
                            executor_binding=str(
                                record.executor_binding or ""
                            ),
                            source_task_ids=tuple(task.dependencies),
                            started_at=started_at,
                            completed_at=datetime.now(
                                timezone.utc
                            ).isoformat(),
                            status="OUTPUT_VALIDATION",
                        )
                        self._audit.append({
                            "event": "TASK_OUTPUT_VALIDATION",
                            "authority": "DEEPSEEK_HARNESS",
                            "mission_id": self.spec.mission_id,
                            "task_id": task_id,
                            "functional_role": task.functional_role,
                            "agent_turn": agent_turn,
                            "status": "OUTPUT_VALIDATION",
                            "failure_mode": (
                                "ROOT_CAUSE_REQUIRES_REAL_TOOL_EVIDENCE"
                            ),
                            "evidence_ref": validation_row["evidence_ref"],
                        })
                        previous_output = extract_agent_output_text(result)
                        continue

            output_validation = validate_task_output_contract(
                functional_role=task.functional_role,
                result=validation_subject,
            )
            if (
                not output_validation.required
                or output_validation.final_output_valid
            ):
                normalized_result = _jsonable(result)
                loop_metrics = {
                    "agent_turns": agent_turn,
                    "tool_calls": tool_calls,
                    "tool_request_count": len(seen_request_ids),
                    "provider_calls": provider_calls,
                    "max_agent_turns": max_agent_turns,
                    "max_tool_calls": max_tool_calls,
                    "max_provider_calls": MAX_PROVIDER_CALLS,
                    "task_wall_clock_ms": round(
                        (time.perf_counter() - task_started_perf) * 1000.0,
                        3,
                    ),
                    "final_output_schema": (
                        output_validation.final_output_schema
                    ),
                    "final_output_valid": (
                        output_validation.final_output_valid
                    ),
                }
                if isinstance(normalized_result, dict):
                    persisted_result = {
                        **normalized_result,
                        "agent_loop": loop_metrics,
                    }
                else:
                    persisted_result = {
                        "provider_result": normalized_result,
                        "agent_loop": loop_metrics,
                    }
                inherited_evidence_refs = list(dict.fromkeys([
                    *(
                        str(ref).strip()
                        for ref in tuple(task.input_refs or ())
                        if str(ref).strip()
                    ),
                    *(
                        str(ref).strip()
                        for ref in (
                            turn_context.get("evidence_refs") or ()
                        )
                        if str(ref).strip()
                    ),
                    *(
                        str(ref).strip()
                        for tool_result in tool_results
                        for ref in (
                            tool_result.get("output_refs") or ()
                        )
                        if str(ref).strip()
                    ),
                ]))
                if isinstance(persisted_result, dict) and inherited_evidence_refs:
                    existing_refs = persisted_result.get("evidence_refs")
                    if isinstance(existing_refs, str):
                        existing_refs = [existing_refs]
                    elif not isinstance(existing_refs, (list, tuple)):
                        existing_refs = []
                    persisted_result["evidence_refs"] = list(dict.fromkeys([
                        *(
                            str(ref).strip()
                            for ref in existing_refs
                            if str(ref).strip()
                        ),
                        *inherited_evidence_refs,
                    ]))

                result_row = self._persist_result(
                    task_id=task_id,
                    capability_id=capability_id,
                    agent_id=record.agent_id,
                    routing_id=decision.routing_id,
                    authorization_id=last_authorization_id,
                    elapsed_seconds=(
                        time.perf_counter() - task_started_perf
                    ),
                    result=persisted_result,
                    idempotency_key=task.idempotency_key,
                    capability_version=task.capability_version,
                    retry_count=retry_attempt,
                    skill_id=record.skill_id,
                    executor_binding=str(record.executor_binding or ""),
                    source_task_ids=tuple(task.dependencies),
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                session.complete(
                    final_output_schema=(
                        output_validation.final_output_schema
                    ),
                    output_artifact_ref=result_row["evidence_ref"],
                    tool_results=tool_results,
                )
                audit = {
                    "event": "TASK_COMPLETED",
                    "authority": "DEEPSEEK_HARNESS",
                    "mission_id": self.spec.mission_id,
                    "task_id": task_id,
                    "task_class": task.task_class,
                    "functional_role": task.functional_role,
                    "capability_id": capability_id,
                    "agent_id": record.agent_id,
                    "agent_instance_id": session.agent_instance_id,
                    "agent_session_ref": session.artifact_ref,
                    "runtime": "hermes",
                    "routing_id": decision.routing_id,
                    "authorization_id": last_authorization_id,
                    "parent_authorization_id": self.parent_authorization.authorization_id,
                    "executor_binding": record.executor_binding,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": round(
                        time.perf_counter() - task_started_perf,
                        6,
                    ),
                    "success": True,
                    "evidence_quality": "REGISTRY_BOUND_CAPABILITY_ADAPTER",
                    "idempotency_key": task.idempotency_key,
                    "capability_version": task.capability_version,
                    "human_correction": False,
                    "review_rejection": False,
                    "retry_count": retry_attempt,
                    "policy_violations": 0,
                    "cost": 0.0,
                    "evidence_ref": result_row["evidence_ref"],
                    "agent_loop": loop_metrics,
                }
                self._audit.append(audit)
                return {
                    "authority": "DEEPSEEK_HARNESS",
                    "executed": True,
                    "reused": False,
                    "capability_id": capability_id,
                    "agent_id": record.agent_id,
                    "agent_instance_id": session.agent_instance_id,
                    "agent_session_ref": session.artifact_ref,
                    "routing_id": decision.routing_id,
                    "authorization_id": last_authorization_id,
                    "executor_binding": record.executor_binding,
                    "evidence_ref": result_row["evidence_ref"],
                    "result": persisted_result,
                    "agent_loop": loop_metrics,
                }

            try:
                request = extract_tool_request(
                    result,
                    mission_id=self.spec.mission_id,
                    task_id=task.task_id,
                    agent_id=str(record.agent_id or ""),
                    capability_id=task.capability_id,
                )
            except AgentToolAuthorizationError as exc:
                failure_result = {
                    "provider_result": _jsonable(result),
                    "output_contract_validation": (
                        output_validation.to_dict()
                    ),
                    "tool_error": {
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1200],
                    },
                    "agent_loop": {
                        "agent_turns": agent_turn,
                        "tool_calls": tool_calls,
                        "provider_calls": provider_calls,
                    },
                }
                self._persist_loop_failure(
                    task=task,
                    record=record,
                    decision=decision,
                    authorization_id=last_authorization_id,
                    elapsed=time.perf_counter() - task_started_perf,
                    started_at=started_at,
                    retry_attempt=retry_attempt,
                    status="FAILED_TOOL",
                    result=failure_result,
                    failure_mode=type(exc).__name__,
                )
                raise DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode=type(exc).__name__,
                    retry_attempt=retry_attempt,
                    retry_allowed=False,
                    requires_harness_replan=True,
                ) from exc
            except AgentToolRequestError as exc:
                candidate = extract_tool_request_candidate(result)
                if candidate is not None and agent_turn < max_agent_turns:
                    output_validation_feedback = {
                        "schema": "ToolRequestValidationFeedback/v1",
                        "expected_schema": TOOL_REQUEST_SCHEMA,
                        "errors": [str(exc)[:240]],
                        "received_keys": sorted(
                            str(key) for key in candidate.keys()
                        ),
                        "instruction": (
                            "Return ONLY one corrected ToolRequestEnvelope JSON "
                            "object. Do not include prose, tool results, or final "
                            "evidence in the same response. Every required field "
                            "must be top-level and the tool must remain within "
                            "the Harness allowlist."
                        ),
                    }
                    validation_row = self._persist_result(
                        task_id=task_id,
                        capability_id=capability_id,
                        agent_id=record.agent_id,
                        routing_id=decision.routing_id,
                        authorization_id=last_authorization_id,
                        elapsed_seconds=(
                            time.perf_counter() - task_started_perf
                        ),
                        result={
                            "provider_result": _jsonable(result),
                            "output_contract_validation": (
                                output_validation.to_dict()
                            ),
                            "output_validation_feedback": (
                                output_validation_feedback
                            ),
                            "tool_request_candidate": candidate,
                            "agent_loop": {
                                "agent_turns": agent_turn,
                                "tool_calls": tool_calls,
                                "provider_calls": provider_calls,
                            },
                        },
                        idempotency_key=task.idempotency_key,
                        capability_version=task.capability_version,
                        retry_count=retry_attempt,
                        skill_id=record.skill_id,
                        executor_binding=str(record.executor_binding or ""),
                        source_task_ids=tuple(task.dependencies),
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        status="OUTPUT_VALIDATION",
                    )
                    self._audit.append({
                        "event": "TASK_TOOL_REQUEST_VALIDATION",
                        "authority": "DEEPSEEK_HARNESS",
                        "mission_id": self.spec.mission_id,
                        "task_id": task_id,
                        "task_class": task.task_class,
                        "functional_role": task.functional_role,
                        "capability_id": capability_id,
                        "agent_id": record.agent_id,
                        "agent_turn": agent_turn,
                        "status": "OUTPUT_VALIDATION",
                        "evidence_ref": validation_row["evidence_ref"],
                        "tool_request_error": str(exc)[:240],
                    })
                    previous_output = extract_agent_output_text(result)
                    continue

                failure_result = {
                    "provider_result": _jsonable(result),
                    "output_contract_validation": (
                        output_validation.to_dict()
                    ),
                    "tool_error": {
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1200],
                    },
                    "agent_loop": {
                        "agent_turns": agent_turn,
                        "tool_calls": tool_calls,
                        "provider_calls": provider_calls,
                    },
                }
                self._persist_loop_failure(
                    task=task,
                    record=record,
                    decision=decision,
                    authorization_id=last_authorization_id,
                    elapsed=time.perf_counter() - task_started_perf,
                    started_at=started_at,
                    retry_attempt=retry_attempt,
                    status="FAILED_TOOL",
                    result=failure_result,
                    failure_mode=type(exc).__name__,
                )
                raise DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode=type(exc).__name__,
                    retry_attempt=retry_attempt,
                    retry_allowed=False,
                    requires_harness_replan=True,
                ) from exc

            if request is None:
                correction_candidate = extract_exact_json_output(result)
                if (
                    correction_candidate is not None
                    and agent_turn < max_agent_turns
                ):
                    output_validation_feedback = {
                        "schema": "TaskOutputValidationFeedback/v1",
                        "expected_schema": output_validation.expected_schema,
                        "errors": list(output_validation.errors),
                        "received_keys": sorted(
                            str(key)
                            for key in correction_candidate.keys()
                        ),
                        "instruction": (
                            "Return ONLY a corrected final JSON object. The "
                            "top-level field schema MUST equal expected_schema "
                            "exactly. Do not invent tool execution and do not "
                            "omit required fields."
                        ),
                    }
                    validation_row = self._persist_result(
                        task_id=task_id,
                        capability_id=capability_id,
                        agent_id=record.agent_id,
                        routing_id=decision.routing_id,
                        authorization_id=last_authorization_id,
                        elapsed_seconds=(
                            time.perf_counter() - task_started_perf
                        ),
                        result={
                            "provider_result": _jsonable(result),
                            "output_contract_validation": (
                                output_validation.to_dict()
                            ),
                            "output_validation_feedback": (
                                output_validation_feedback
                            ),
                            "agent_loop": {
                                "agent_turns": agent_turn,
                                "tool_calls": tool_calls,
                                "provider_calls": provider_calls,
                            },
                        },
                        idempotency_key=task.idempotency_key,
                        capability_version=task.capability_version,
                        retry_count=retry_attempt,
                        skill_id=record.skill_id,
                        executor_binding=str(record.executor_binding or ""),
                        source_task_ids=tuple(task.dependencies),
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        status="OUTPUT_VALIDATION",
                    )
                    self._audit.append({
                        "event": "TASK_OUTPUT_VALIDATION",
                        "authority": "DEEPSEEK_HARNESS",
                        "mission_id": self.spec.mission_id,
                        "task_id": task_id,
                        "task_class": task.task_class,
                        "functional_role": task.functional_role,
                        "capability_id": capability_id,
                        "agent_id": record.agent_id,
                        "agent_turn": agent_turn,
                        "status": "OUTPUT_VALIDATION",
                        "evidence_ref": validation_row["evidence_ref"],
                        "output_contract_validation": (
                            output_validation.to_dict()
                        ),
                    })
                    previous_output = extract_agent_output_text(result)
                    continue

                invalid_result = {
                    "provider_result": _jsonable(result),
                    "output_contract_validation": (
                        output_validation.to_dict()
                    ),
                    "agent_loop": {
                        "agent_turns": agent_turn,
                        "tool_calls": tool_calls,
                        "provider_calls": provider_calls,
                    },
                }
                result_row = self._persist_result(
                    task_id=task_id,
                    capability_id=capability_id,
                    agent_id=record.agent_id,
                    routing_id=decision.routing_id,
                    authorization_id=last_authorization_id,
                    elapsed_seconds=(
                        time.perf_counter() - task_started_perf
                    ),
                    result=invalid_result,
                    idempotency_key=task.idempotency_key,
                    capability_version=task.capability_version,
                    retry_count=retry_attempt,
                    skill_id=record.skill_id,
                    executor_binding=str(record.executor_binding or ""),
                    source_task_ids=tuple(task.dependencies),
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    status="FAILED_CONTRACT",
                )
                self._audit.append({
                    "event": "TASK_FAILED_CONTRACT",
                    "authority": "DEEPSEEK_HARNESS",
                    "mission_id": self.spec.mission_id,
                    "task_id": task_id,
                    "task_class": task.task_class,
                    "functional_role": task.functional_role,
                    "capability_id": capability_id,
                    "routing_id": decision.routing_id,
                    "authorization_id": last_authorization_id,
                    "status": "FAILED_CONTRACT",
                    "FALSE_COMPLETED_PREVENTED": "PASS",
                    "evidence_ref": result_row["evidence_ref"],
                    "output_contract_validation": (
                        output_validation.to_dict()
                    ),
                })
                violation = TaskOutputContractViolation(
                    output_validation
                )
                raise DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode=type(violation).__name__,
                    retry_attempt=retry_attempt,
                    retry_allowed=False,
                    requires_harness_replan=True,
                ) from violation

            session.record_tool_request(request.to_dict())
            if request.request_id in seen_request_ids:
                exc = AgentToolRequestError(
                    "DUPLICATE_TOOL_REQUEST_ID:"
                    + request.request_id
                )
                self._persist_loop_failure(
                    task=task,
                    record=record,
                    decision=decision,
                    authorization_id=last_authorization_id,
                    elapsed=time.perf_counter() - task_started_perf,
                    started_at=started_at,
                    retry_attempt=retry_attempt,
                    status="FAILED_TOOL",
                    result={
                        "provider_result": _jsonable(result),
                        "tool_request": request.to_dict(),
                        "error": str(exc),
                    },
                    failure_mode=type(exc).__name__,
                )
                raise DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode=type(exc).__name__,
                    retry_attempt=retry_attempt,
                    retry_allowed=False,
                    requires_harness_replan=True,
                ) from exc
            request_fingerprint = tool_request_fingerprint(request)
            if request_fingerprint in tool_result_by_fingerprint:
                seen_request_ids.add(request.request_id)
                previous_tool_result = tool_result_by_fingerprint[
                    request_fingerprint
                ]
                reuse_started = utcnow()
                reused_envelope = build_tool_result_envelope(
                    request=request,
                    tool_id=request.tool_or_capability_id,
                    operation=request.operation,
                    authorization_id=str(
                        previous_tool_result.get("authorization_id") or ""
                    ),
                    output_refs=tuple(
                        str(item)
                        for item in (
                            previous_tool_result.get("output_refs") or ()
                        )
                        if str(item).strip()
                    ),
                    result_payload={
                        "reused_from_request_id": (
                            previous_tool_result.get("request_id")
                        ),
                        "reused_content_sha256": (
                            previous_tool_result.get("content_sha256")
                        ),
                        "reused_output_refs": list(
                            previous_tool_result.get("output_refs") or ()
                        ),
                        "duplicate_tool_execution_avoided": True,
                        "instruction": (
                            "No new evidence was produced because this tool "
                            "request is semantically identical to a prior "
                            "request in the same task. Use the already observed "
                            "bounded result and produce the final typed output "
                            "or request a materially different tool/input."
                        ),
                    },
                    status="REUSED",
                    started_at=reuse_started,
                    finished_at=utcnow(),
                    error=None,
                ).to_dict()
                reuse_ref = self._persist_tool_result(
                    task_id=task.task_id,
                    request_id=request.request_id,
                    payload=reused_envelope,
                )
                reused_envelope["output_refs"] = list(dict.fromkeys([
                    *list(reused_envelope.get("output_refs") or ()),
                    reuse_ref,
                ]))
                self._persist_tool_result(
                    task_id=task.task_id,
                    request_id=request.request_id,
                    payload=reused_envelope,
                )
                tool_results.append(reused_envelope)
                session.record_tool_result(reused_envelope)
                self._audit.append({
                    "event": "TOOL_RESULT_REUSED",
                    "authority": "DEEPSEEK_HARNESS",
                    "mission_id": self.spec.mission_id,
                    "task_id": task_id,
                    "functional_role": task.functional_role,
                    "agent_turn": agent_turn,
                    "request_id": request.request_id,
                    "tool_id": request.tool_or_capability_id,
                    "operation": request.operation,
                    "status": "REUSED",
                    "tool_result_ref": reuse_ref,
                    "DUPLICATE_TOOL_EXECUTION_AVOIDED": "PASS",
                })
                output_validation_feedback = None
                previous_output = extract_agent_output_text(result)
                continue

            if tool_calls >= max_tool_calls:
                exc = AgentToolBudgetExceeded("MAX_TOOL_CALLS")
                self._persist_loop_failure(
                    task=task,
                    record=record,
                    decision=decision,
                    authorization_id=last_authorization_id,
                    elapsed=time.perf_counter() - task_started_perf,
                    started_at=started_at,
                    retry_attempt=retry_attempt,
                    status="FAILED_BUDGET",
                    result={
                        "provider_result": _jsonable(result),
                        "tool_request": request.to_dict(),
                        "agent_loop": {
                            "agent_turns": agent_turn,
                            "tool_calls": tool_calls,
                            "provider_calls": provider_calls,
                        },
                    },
                    failure_mode="MAX_TOOL_CALLS",
                )
                raise DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode=type(exc).__name__,
                    retry_attempt=retry_attempt,
                    retry_allowed=False,
                    requires_harness_replan=True,
                ) from exc

            seen_request_ids.add(request.request_id)
            waiting_row = self._persist_result(
                task_id=task_id,
                capability_id=capability_id,
                agent_id=record.agent_id,
                routing_id=decision.routing_id,
                authorization_id=last_authorization_id,
                elapsed_seconds=time.perf_counter() - task_started_perf,
                result={
                    "provider_result": _jsonable(result),
                    "tool_request": request.to_dict(),
                    "output_contract_validation": (
                        output_validation.to_dict()
                    ),
                    "agent_loop": {
                        "agent_turns": agent_turn,
                        "tool_calls": tool_calls,
                        "provider_calls": provider_calls,
                    },
                },
                idempotency_key=task.idempotency_key,
                capability_version=task.capability_version,
                retry_count=retry_attempt,
                skill_id=record.skill_id,
                executor_binding=str(record.executor_binding or ""),
                source_task_ids=tuple(task.dependencies),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                status="WAITING_TOOL",
            )
            self._audit.append({
                "event": "TASK_WAITING_TOOL",
                "authority": "DEEPSEEK_HARNESS",
                "mission_id": self.spec.mission_id,
                "task_id": task_id,
                "functional_role": task.functional_role,
                "capability_id": capability_id,
                "agent_id": record.agent_id,
                "agent_turn": agent_turn,
                "request_id": request.request_id,
                "tool_id": request.tool_or_capability_id,
                "status": "WAITING_TOOL",
                "evidence_ref": waiting_row["evidence_ref"],
            })

            try:
                tool_result = self._execute_agent_tool_request(
                    task=task,
                    request=request,
                    parent_context=turn_context,
                    agent_turn=agent_turn,
                )
            except (
                AgentToolRequestError,
                AgentToolAuthorizationError,
                AgentToolBudgetExceeded,
            ) as exc:
                self._persist_loop_failure(
                    task=task,
                    record=record,
                    decision=decision,
                    authorization_id=last_authorization_id,
                    elapsed=time.perf_counter() - task_started_perf,
                    started_at=started_at,
                    retry_attempt=retry_attempt,
                    status=(
                        "FAILED_BUDGET"
                        if isinstance(exc, AgentToolBudgetExceeded)
                        else "FAILED_TOOL"
                    ),
                    result={
                        "provider_result": _jsonable(result),
                        "tool_request": request.to_dict(),
                        "tool_error": {
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:1200],
                        },
                    },
                    failure_mode=type(exc).__name__,
                )
                raise DelegatedCapabilityFailure(
                    task_id=task_id,
                    capability_id=capability_id,
                    failure_mode=type(exc).__name__,
                    retry_attempt=retry_attempt,
                    retry_allowed=False,
                    requires_harness_replan=True,
                ) from exc

            tool_calls += 1
            tool_results.append(tool_result)
            session.record_tool_result(tool_result)
            tool_result_by_fingerprint[request_fingerprint] = tool_result
            output_validation_feedback = None
            previous_output = extract_agent_output_text(result)

        failure_result = {
            "provider_result": _jsonable(last_result),
            "error": "MAX_AGENT_TURNS",
            "agent_loop": {
                "agent_turns": max_agent_turns,
                "tool_calls": tool_calls,
                "provider_calls": provider_calls,
            },
        }
        self._persist_loop_failure(
            task=task,
            record=record,
            decision=decision,
            authorization_id=last_authorization_id,
            elapsed=time.perf_counter() - task_started_perf,
            started_at=started_at,
            retry_attempt=retry_attempt,
            status="FAILED_BUDGET",
            result=failure_result,
            failure_mode="MAX_AGENT_TURNS",
        )
        raise DelegatedCapabilityFailure(
            task_id=task_id,
            capability_id=capability_id,
            failure_mode="AgentToolBudgetExceeded",
            retry_attempt=retry_attempt,
            retry_allowed=False,
            requires_harness_replan=True,
        )

    def retry_delegated_capability(
        self,
        *,
        failure: DelegatedCapabilityFailure,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task = self._task(failure.task_id)
        if failure.capability_id != task.capability_id:
            raise PermissionError("retry capability differs from TaskEnvelope")
        if failure.requires_harness_replan or not failure.retry_allowed:
            raise PermissionError(
                "retry exhausted; capability/strategy change requires DeepSeek Harness replan"
            )
        return self.execute_delegated_capability(
            task_id=failure.task_id,
            capability_id=failure.capability_id,
            payload=payload,
            retry_attempt=failure.retry_attempt + 1,
        )

    def parent_context(self, *, task_id: str) -> dict[str, Any]:
        context_started = time.perf_counter()
        task = self._task(task_id)
        parents: list[dict[str, Any]] = []
        max_bytes = int(self.spec.budgets.get("context_bytes", 65536))
        used = 0
        artifact_load_ms = 0.0
        duplicate_bytes = 0
        seen_tasks: set[str] = set()
        seen_hashes: set[str] = set()

        def resolve(parent_id: str, *, direct: bool) -> None:
            nonlocal used, artifact_load_ms, duplicate_bytes
            if parent_id in seen_tasks:
                return
            seen_tasks.add(parent_id)
            rows = self._task_results.get(parent_id) or []
            if not rows:
                raise DependencyArtifactMissing(
                    task_id=task_id,
                    dependency_task_id=parent_id,
                    resolution_attempts=(f"result-snapshot:{parent_id}",),
                )
            row = rows[-1]
            source_task = self._task(parent_id)
            task_result_ref = str(row.get("task_result_ref") or "").strip()
            if not task_result_ref:
                now = datetime.now(timezone.utc).isoformat()
                upgraded = build_task_result_envelope(
                    mission_id=self.spec.mission_id,
                    task_id=parent_id,
                    capability_id=str(row.get("capability_id") or source_task.capability_id),
                    agent_id=row.get("agent_id"),
                    skill_id=source_task.selected_skill_id,
                    executor_binding=source_task.selected_executor_binding,
                    status=str(row.get("status") or "COMPLETED"),
                    started_at=now,
                    completed_at=now,
                    elapsed_ms=float(row.get("elapsed_seconds") or 0.0) * 1000.0,
                    result=row.get("result"),
                    source_task_ids=tuple(source_task.dependencies),
                    authorization_id=str(row.get("authorization_id") or self.parent_authorization.authorization_id),
                )
                upgraded_record = persist_task_result_envelope(
                    upgraded, artifact_dir=self.artifact_dir, index=len(rows)
                )
                task_result_ref = upgraded_record["task_result_ref"]
                row["task_result_ref"] = task_result_ref
                row["task_result_sha256"] = upgraded_record["content_sha256"]
            load_started = time.perf_counter()
            try:
                envelope = load_task_result_envelope(
                    artifact_dir=self.artifact_dir,
                    task_result_ref=task_result_ref,
                )
            except (FileNotFoundError, ValueError, PermissionError) as exc:
                raise DependencyArtifactMissing(
                    task_id=task_id,
                    dependency_task_id=parent_id,
                    resolution_attempts=(
                        f"result-snapshot:{parent_id}",
                        task_result_ref,
                        type(exc).__name__,
                    ),
                ) from exc
            artifact_load_ms += (time.perf_counter() - load_started) * 1000.0
            digest = str(envelope.get("content_sha256") or "")
            candidate = {
                "task_id": parent_id,
                "functional_role": source_task.functional_role,
                "input_refs": list(source_task.input_refs or ()),
                "capability_id": envelope.get("capability_id"),
                "agent_id": envelope.get("agent_id"),
                "skill_id": envelope.get("skill_id"),
                "task_result_ref": task_result_ref,
                "content_sha256": digest,
                "result_summary": envelope.get("result_summary"),
                "output_artifact_refs": list(envelope.get("output_artifact_refs") or ()),
                "evidence_refs": list(envelope.get("evidence_refs") or ()),
                "metrics_refs": list(envelope.get("metrics_refs") or ()),
                "source_task_ids": list(envelope.get("source_task_ids") or ()),
                "direct_dependency": bool(direct),
                "result": envelope.get("result_payload"),
            }
            size = len(json.dumps(candidate, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
            if digest in seen_hashes:
                duplicate_bytes += size
                return
            seen_hashes.add(digest)
            if used + size > max_bytes:
                candidate.pop("result", None)
                candidate["result_omitted"] = "CONTEXT_BUDGET"
                size = len(json.dumps(candidate, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
            parents.append(candidate)
            used += size
            for source_id in envelope.get("source_task_ids") or ():
                resolve(str(source_id), direct=False)

        for parent_id in task.dependencies:
            resolve(str(parent_id), direct=True)

        record = self.registry.get(task.capability_id)
        if record is None:
            raise PermissionError("Hermes task capability disappeared from Registry")
        artifact_ref = next((str(ref) for ref in task.input_refs if str(ref).strip()), None)
        bounded = build_bounded_memory_context(
            goal_id=self.spec.goal_id,
            domain=record.domain,
            task_class=f"hermes:{task.task_id}",
            capability_id=task.capability_id,
            agent_id=task.selected_agent_id,
            artifact_ref=artifact_ref,
            intent=task.objective,
            max_bytes=max(4096, min(max_bytes // 2, 32768)),
        ).to_dict()
        profile = HermesProfileFactory(registry=self.registry).project_task(task)
        evidence_refs = list(dict.fromkeys([
            *[str(item.get("task_result_ref") or "") for item in parents if str(item.get("task_result_ref") or "").strip()],
            *[str(ref) for item in parents for ref in (
                list(item.get("output_artifact_refs") or ())
                + list(item.get("evidence_refs") or ())
                + list(item.get("metrics_refs") or ())
            ) if str(ref).strip()],
            *[ref for item in bounded["operational_memory"] for ref in (item.get("evidence_refs") or ())],
            *[ref for item in bounded["conversation_memory"] for ref in (item.get("evidence_refs") or ())],
            *[ref for item in bounded["artifact_lineage_memory"] for ref in (item.get("evidence_refs") or ())],
        ]))
        dependency_result_refs = [
            {
                "task_id": item.get("task_id"),
                "task_result_ref": item.get("task_result_ref"),
                "content_sha256": item.get("content_sha256"),
                "direct_dependency": bool(item.get("direct_dependency")),
            }
            for item in parents
        ]
        full_dependency_alias_bytes = len(json.dumps(
            parents,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8"))
        ref_dependency_alias_bytes = len(json.dumps(
            dependency_result_refs,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8"))
        dependency_metrics = {
            "DEPENDENCY_ARTIFACT_COUNT": len(parents),
            "DEPENDENCY_CONTEXT_BYTES": used,
            "DEPENDENCY_CONTEXT_BUILD_MS": round((time.perf_counter() - context_started) * 1000.0, 3),
            "DEPENDENCY_ARTIFACT_LOAD_MS": round(artifact_load_ms, 3),
            "DUPLICATE_HANDOFF_BYTES": duplicate_bytes,
            "DEPENDENCY_ALIAS_BYTES_AVOIDED": max(
                0,
                full_dependency_alias_bytes - ref_dependency_alias_bytes,
            ),
        }
        dependency_fingerprint = sha256(json.dumps({
            "task_id": task_id,
            "parents": [{"task_id": item.get("task_id"), "content_sha256": item.get("content_sha256")} for item in parents],
        }, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "goal_id": self.spec.goal_id,
            "task": {
                "objective": task.objective,
                "capability_id": task.capability_id,
                "agent_id": task.selected_agent_id,
                "skill_id": task.selected_skill_id,
                "action": task.action,
            },
            "parent_handoffs": parents,
            # Backward-compatible dependency_results is intentionally refs-only.
            # The canonical payload lives once in parent_handoffs and in the
            # content-addressed TaskResultEnvelope artifact.
            "dependency_results": dependency_result_refs,
            "dependency_metrics": dependency_metrics,
            "dependency_context_sha256": dependency_fingerprint,
            "relevant_memory": {
                "operational_memory": bounded["operational_memory"],
                "knowledge_memory": bounded["knowledge_memory"],
                "artifact_lineage_memory": bounded["artifact_lineage_memory"],
                "competence_records": bounded["competence_records"],
            },
            "relevant_human_decisions": bounded["conversation_memory"],
            "evidence_refs": evidence_refs[:24],
            "allowed_tools": list(profile.allowed_tools),
            "memory_write": profile.memory_write,
            "input_refs": list(task.input_refs),
            "budget_bytes": max_bytes,
            "used_bytes": used + int(bounded.get("used_bytes") or 0),
            "bounded_memory_context": True,
        }

    def submit_handoff(
        self,
        *,
        from_task_id: str,
        to_task_id: str,
        evidence_refs: list[str] | tuple[str, ...],
        summary: str,
    ) -> dict[str, Any]:
        source = self._task(from_task_id)
        target = self._task(to_task_id)
        target_parents = set(target.dependencies)
        dynamic_parent = self._child_parent.get(to_task_id)
        if from_task_id not in target_parents and dynamic_parent != from_task_id:
            raise PermissionError(
                "Hermes handoff must follow authorized dependency lineage"
            )
        refs = tuple(dict.fromkeys(
            str(ref).strip()
            for ref in evidence_refs
            if str(ref).strip()
        ))
        rows = self._task_results.get(from_task_id, ())
        known_refs = {str(ref) for row in rows for ref in (row.get("evidence_ref"), row.get("task_result_ref")) if str(ref or "").strip()}
        if not refs or not set(refs).issubset(known_refs):
            raise PermissionError(
                "Hermes handoff may reference only observed source-task evidence"
            )
        latest = rows[-1]
        source_record = self.registry.get(source.capability_id)
        if source_record is None:
            raise PermissionError("Handoff producer capability disappeared from Registry")
        typed = TypedHandoff(
            from_task_id=from_task_id,
            to_task_id=to_task_id,
            evidence_refs=refs,
            result_ref=str(latest.get("task_result_ref") or latest["evidence_ref"]),
            output_contract=str(source_record.output_contract or ""),
            summary=str(summary).strip()[:1600],
            acceptance_state="ACCEPTED_FOR_DEPENDENCY",
            artifact_lineage={
                "evidence_ref": latest["evidence_ref"],
                "sha256": latest["sha256"],
                "authorization_id": latest["authorization_id"],
                "routing_id": latest["routing_id"],
            },
            producer_capability_id=source.capability_id,
            producer_agent_id=source.selected_agent_id,
            producer_skill_id=source.selected_skill_id,
            producer_version=str(source_record.version or "1"),
            observed_at=datetime.now(timezone.utc).isoformat(),
        )
        body = (
            f"TYPED_HANDOFF={json.dumps(typed.to_dict(), ensure_ascii=False, default=str)}"
        )
        comment_id = self.board.comment(
            self.task_mapping[to_task_id],
            author=(
                "hermes:"
                + str(
                    source.selected_agent_id
                    or source.selected_skill_id
                    or from_task_id
                )
            ),
            body=body,
        )
        item = {
            **typed.to_dict(),
            "comment_id": comment_id,
        }
        self._handoffs.append(item)
        return item

    def propose_child_task(
        self,
        *,
        parent_task_id: str,
        child: dict[str, Any],
        depth: int | None = None,
    ) -> dict[str, Any]:
        parent = self._task(parent_task_id)
        parent_depth = self._child_depth.get(parent_task_id, 0)
        proposed_depth = int(depth if depth is not None else parent_depth + 1)
        validated = self.spec.validate_child_task(
            parent_task_id=(
                self._child_parent.get(parent_task_id)
                if parent_task_id in self._child_tasks
                else parent_task_id
            ),
            parent_envelope=parent,
            child=child,
            depth=proposed_depth,
            existing_child_count=len(self._child_tasks),
        )
        if validated.task_id in self.task_mapping or validated.task_id in self._child_tasks:
            existing = self._child_tasks.get(validated.task_id)
            if existing is not None and existing.idempotency_key == validated.idempotency_key:
                return {
                    "status": "REUSED",
                    "task": existing.to_dict(),
                    "board_task_id": self.task_mapping[validated.task_id],
                    "DUPLICATE_AGENT_EXECUTION_AVOIDED": "PASS",
                }
            raise PermissionError("Hermes child task id collides with existing task")

        record = self.registry.get(validated.capability_id)
        if record is None or not record.execution_enabled:
            raise PermissionError("Hermes child capability is not executable")
        decision = route_harness_request(
            HarnessRoutingRequest(
                intent=(
                    f"Hermes bounded child of {parent_task_id}: "
                    f"{validated.objective}"
                ),
                authorized_action=validated.action,
                domain=record.domain,
                task_class=validated.task_class,
                goal_id=self.spec.goal_id,
                required_capability_id=validated.capability_id,
                fallback_allowed=False,
                provider_required=False,
                learning_required=True,
            )
        )
        if decision.selected_capability_id != validated.capability_id:
            raise PermissionError(
                "Child proposal requires Harness replan before capability substitution"
            )
        if decision.selected_executor_binding != record.executor_binding:
            raise PermissionError("Child routing escaped Registry executor binding")
        selected = dict(
            decision.policy_metadata.get("selected_implementation") or {}
        )
        raw_key = json.dumps(
            {
                "mission_id": self.spec.mission_id,
                "parent_task_id": parent_task_id,
                "task_id": validated.task_id,
                "capability_id": validated.capability_id,
                "version": str(record.version or "1"),
                "objective": validated.objective,
                "input_refs": list(validated.input_refs),
                "read_scope": list(validated.read_scope),
                "write_scope": list(validated.write_scope),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        idempotency_key = (
            validated.idempotency_key
            or "child:" + sha256(raw_key.encode("utf-8")).hexdigest()
        )
        routed = RoutedCollaborationTask(
            task_id=validated.task_id,
            capability_id=validated.capability_id,
            action=validated.action,
            objective=validated.objective,
            dependencies=(parent_task_id,),
            input_refs=validated.input_refs,
            expected_output=validated.expected_output,
            routing_id=decision.routing_id,
            candidate_capability_ids=decision.candidate_capability_ids,
            selected_executor_binding=str(record.executor_binding),
            selected_agent_id=selected.get("agent_id"),
            selected_skill_id=selected.get("skill_id"),
            evidence_expectations=decision.evidence_expectations,
            task_class=validated.task_class,
            required_capability_description=validated.required_capability_description,
            acceptance_criteria=validated.acceptance_criteria,
            read_scope=validated.read_scope,
            write_scope=validated.write_scope,
            allowed_tools=validated.allowed_tools,
            allowed_side_effects=validated.allowed_side_effects,
            forbidden_side_effects=validated.forbidden_side_effects,
            time_budget_seconds=validated.time_budget_seconds,
            cost_budget=validated.cost_budget,
            context_budget_bytes=validated.context_budget_bytes,
            tool_budget=validated.tool_budget,
            retry_budget=validated.retry_budget,
            evidence_contract=validated.evidence_contract,
            review_policy=validated.review_policy,
            risk_side_effect_class=validated.risk_side_effect_class,
            idempotency_key=idempotency_key,
            expires_at=validated.expires_at or self.spec.expires_at,
            human_gate_policy=validated.human_gate_policy,
            mission_id=self.spec.mission_id,
            goal_id=self.spec.goal_id,
            capability_version=str(record.version or "1"),
            supports_parallelism=bool(record.supports_parallelism),
            supports_retry=bool(record.supports_retry),
            supports_resume=bool(record.supports_resume),
            supports_review=bool(record.supports_review),
            selection_evidence={
                "routing_id": decision.routing_id,
                "selected_implementation": selected,
                "bounded_child_of": parent_task_id,
            },
        )
        assignee = str(
            routed.selected_agent_id
            or routed.selected_skill_id
            or routed.capability_id
        )
        board_task_id = self.board.create_task(
            title=routed.objective[:160],
            body=json.dumps(routed.to_dict(), ensure_ascii=False, default=str),
            assignee=assignee,
            parents=(self.task_mapping[parent_task_id],),
            idempotency_key=idempotency_key,
        )
        self._child_tasks[routed.task_id] = routed
        self._child_parent[routed.task_id] = parent_task_id
        self._child_depth[routed.task_id] = proposed_depth
        self.task_mapping[routed.task_id] = board_task_id
        self._audit.append({
            "event": "CHILD_TASK_PROPOSED",
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": self.spec.mission_id,
            "parent_task_id": parent_task_id,
            "task_id": routed.task_id,
            "capability_id": routed.capability_id,
            "routing_id": routed.routing_id,
            "idempotency_key": routed.idempotency_key,
            "depth": proposed_depth,
            "HERMES_AUTHORITY_EXPANSION": "NO",
        })
        return {
            "status": "AUTHORIZED",
            "task": routed.to_dict(),
            "board_task_id": board_task_id,
            "HERMES_SUBDELEGATION_WITHIN_ENVELOPE": "PASS",
            "HERMES_AUTHORITY_EXPANSION": "NO",
        }

    def request_human_input(self, *, task_id: str, question: str, run_id: int) -> dict[str, Any]:
        self._task(task_id)
        normalized = str(question or "").strip()
        if not normalized:
            raise ValueError("human question is required")
        board_task_id = self.task_mapping[task_id]
        if not self.board.block(board_task_id, reason=normalized, run_id=run_id, kind="needs_input"):
            raise RuntimeError("Hermes task could not enter human-input block")
        human_authorization = issue_harness_authorization(
            authorized_action="EXECUTION",
            subject=f"human-surface:{HUMAN_SURFACE}",
            harness_decision_id=self.spec.harness_decision_id,
            execution_id=self.parent_authorization.execution_id,
            lineage={
                "parent_authorization_id": self.parent_authorization.authorization_id,
                "hermes_mission_id": self.spec.mission_id,
                "hermes_task_id": task_id,
                "goal_id": self.spec.goal_id,
                "human_surface": HUMAN_SURFACE,
                "runtime": "hermes",
            },
        )
        try:
            dispatch = send_harness_message_to_human_group(
                authorization=human_authorization,
                text=(
                    "🧠 BR-no-GTA precisa da sua decisão\n\n"
                    + normalized
                ),
                category="DECISION_REQUEST",
                lineage={
                    "mission_id": self.spec.mission_id,
                    "task_id": task_id,
                    "board_task_id": board_task_id,
                    "goal_id": self.spec.goal_id,
                    "runtime": "hermes",
                },
            )
        finally:
            consume_harness_authorization(human_authorization)
        item = {
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "board_task_id": board_task_id,
            "question": normalized,
            "state": "WAITING_FOR_HUMAN",
            "human_surface": HUMAN_SURFACE,
            "telegram_dispatch": dispatch,
            "fallback_surface": None,
        }
        self._human_requests.append(item)
        return item

    def resume_after_human_input(self, *, task_id: str, answer: str) -> dict[str, Any]:
        self._task(task_id)
        normalized = str(answer or "").strip()
        if not normalized:
            raise ValueError("human answer is required")
        board_task_id = self.task_mapping[task_id]
        self.board.comment(
            board_task_id,
            author="telegram-human",
            body=f"HUMAN_INPUT_RECEIVED={normalized[:1600]}",
        )
        if not self.board.unblock(board_task_id):
            raise RuntimeError("Hermes task could not resume after human input")
        return {
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "status": "RESUMED",
            "answer": normalized,
            "human_surface": HUMAN_SURFACE,
        }

    def observe_task_state(self, *, task_id: str) -> dict[str, Any]:
        self._task(task_id)
        task = self.board.get_task(self.task_mapping[task_id])
        return {
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "board_task_id": task["id"],
            "status": task["status"],
            "assignee": task.get("assignee"),
            "current_run_id": task.get("current_run_id"),
            "parents": list(self._task(task_id).dependencies),
        }

    def audit_snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._audit)

    def handoff_snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._handoffs)

    def human_request_snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._human_requests)

    def result_snapshot(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {
            task_id: tuple(dict(item) for item in rows)
            for task_id, rows in self._task_results.items()
        }
