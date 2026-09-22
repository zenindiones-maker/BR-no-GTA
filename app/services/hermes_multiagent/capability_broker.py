from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import inspect
import json
from pathlib import Path
import time
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    authorization_to_context,
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence, execute_capability
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.telegram_group_human_surface_service import (
    HUMAN_SURFACE,
    send_harness_message_to_human_group,
)

from .contracts import HERMES_RUNTIME_CAPABILITY_ID, HermesMissionExecutionSpec
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


def _binding_callable(binding: str):
    module_name, sep, attr = str(binding or "").rpartition(".")
    if not sep or not module_name or not attr:
        raise PermissionError("Registry executor binding is invalid")
    module = importlib.import_module(module_name)
    executor = getattr(module, attr, None)
    if not callable(executor):
        raise PermissionError("Registry executor binding is not callable")
    actual = f"{getattr(executor, '__module__', '')}.{getattr(executor, '__name__', '')}"
    if actual != binding:
        raise PermissionError("Resolved executor does not match exact Registry binding")
    return executor


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
        self._handoffs: list[dict[str, Any]] = []
        self._human_requests: list[dict[str, Any]] = []
        self._audit: list[dict[str, Any]] = []

    def list_allowed_capabilities(self, *, mission_id: str, task_id: str) -> tuple[dict[str, Any], ...]:
        if str(mission_id) != self.spec.mission_id:
            raise PermissionError("Hermes mission id mismatch")
        task = self.spec.task(task_id)
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

    @staticmethod
    def _authorization_subject(executor, task) -> str:
        params = inspect.signature(executor).parameters
        if "execution_context" in params and "authorization" not in params:
            return f"action:{task.action}"
        return f"capability:{task.capability_id}"

    def _issue_child(self, *, task, record, decision, executor) -> HarnessAuthorization:
        return issue_harness_authorization(
            authorized_action=task.action,
            subject=self._authorization_subject(executor, task),
            harness_decision_id=self.spec.harness_decision_id,
            execution_id=self.parent_authorization.execution_id,
            lineage={
                "parent_authorization_id": self.parent_authorization.authorization_id,
                "hermes_mission_id": self.spec.mission_id,
                "hermes_task_id": task.task_id,
                "goal_id": self.spec.goal_id,
                "routing_id": decision.routing_id,
                "capability_id": task.capability_id,
                "selected_executor_binding": record.executor_binding,
                "agent_id": record.agent_id,
                "skill_id": record.skill_id,
                "runtime": "hermes",
                "base_sha": self.spec.base_sha,
            },
        )

    def _invoke(self, *, executor, task, record, decision, authorization, payload):
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
            "Registry executor signature is not supported by the Hermes Harness broker"
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
    ) -> dict[str, Any]:
        normalized = _jsonable(result)
        index = len(self._task_results.get(task_id, ())) + 1
        relative = Path("capability-results") / f"{task_id}-{index}.json"
        target = self.artifact_dir / relative
        payload = {
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "capability_id": capability_id,
            "agent_id": agent_id,
            "runtime": "hermes",
            "routing_id": routing_id,
            "authorization_id": authorization_id,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "cost": 0.0,
            "policy_violations": 0,
            "result": normalized,
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

    def execute_delegated_capability(
        self,
        *,
        task_id: str,
        capability_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task = self.spec.task(task_id)
        if capability_id != task.capability_id:
            raise PermissionError("Hermes task may execute only its CollaborationPlan capability")
        if any(str(key).lower() in _FORBIDDEN_PAYLOAD_FIELDS for key in payload):
            raise PermissionError("Hermes payload attempted to override authority or routing")
        if capability_id not in self.spec.allowed_capability_ids:
            raise PermissionError("Hermes capability is outside mission lease")
        record, decision = self._route(task)
        executor = _binding_callable(str(record.executor_binding or ""))
        child = self._issue_child(
            task=task,
            record=record,
            decision=decision,
            executor=executor,
        )
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = self._invoke(
                executor=executor,
                task=task,
                record=record,
                decision=decision,
                authorization=child,
                payload=dict(payload),
            )
        finally:
            elapsed = time.perf_counter() - started
            consume_harness_authorization(child)
        result_row = self._persist_result(
            task_id=task_id,
            capability_id=capability_id,
            agent_id=record.agent_id,
            routing_id=decision.routing_id,
            authorization_id=child.authorization_id,
            elapsed_seconds=elapsed,
            result=result,
        )
        audit = {
            "authority": "DEEPSEEK_HARNESS",
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "task_class": f"hermes:{task_id}",
            "capability_id": capability_id,
            "agent_id": record.agent_id,
            "runtime": "hermes",
            "routing_id": decision.routing_id,
            "authorization_id": child.authorization_id,
            "retrieved_memory_ids": [
                item.get("memory_id")
                for item in (
                    (decision.policy_metadata.get("bounded_memory_context") or {}).get("operational_memory") or ()
                )
                if item.get("memory_id")
            ],
            "retrieved_human_decision_ids": [
                item.get("decision_id")
                for item in (
                    (decision.policy_metadata.get("bounded_memory_context") or {}).get("conversation_memory") or ()
                )
                if item.get("decision_id")
            ],
            "parent_authorization_id": self.parent_authorization.authorization_id,
            "executor_binding": record.executor_binding,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 6),
            "success": True,
            "evidence_quality": "REGISTRY_BOUND_EXECUTION",
            "human_correction": False,
            "review_rejection": False,
            "retry_count": 0,
            "policy_violations": 0,
            "cost": 0.0,
            "evidence_ref": result_row["evidence_ref"],
        }
        self._audit.append(audit)
        return {
            "authority": "DEEPSEEK_HARNESS",
            "executed": True,
            "capability_id": capability_id,
            "agent_id": record.agent_id,
            "routing_id": decision.routing_id,
            "authorization_id": child.authorization_id,
            "executor_binding": record.executor_binding,
            "evidence_ref": result_row["evidence_ref"],
            "result": _jsonable(result),
        }

    def parent_context(self, *, task_id: str) -> dict[str, Any]:
        task = self.spec.task(task_id)
        parents: list[dict[str, Any]] = []
        max_bytes = int(self.spec.budgets.get("context_bytes", 65536))
        used = 0
        for parent_id in task.dependencies:
            rows = self._task_results.get(parent_id) or []
            if not rows:
                raise RuntimeError(f"parent output not available: {parent_id}")
            row = rows[-1]
            candidate = {
                "task_id": parent_id,
                "capability_id": row["capability_id"],
                "agent_id": row["agent_id"],
                "evidence_ref": row["evidence_ref"],
                "sha256": row["sha256"],
                "result": row["result"],
            }
            size = len(json.dumps(candidate, ensure_ascii=False, default=str).encode("utf-8"))
            if used + size > max_bytes:
                candidate.pop("result", None)
                candidate["result_omitted"] = "CONTEXT_BUDGET"
                size = len(json.dumps(candidate, ensure_ascii=False).encode("utf-8"))
            parents.append(candidate)
            used += size

        record = self.registry.get(task.capability_id)
        if record is None:
            raise PermissionError("Hermes task capability disappeared from Registry")
        artifact_ref = next(
            (str(ref) for ref in task.input_refs if str(ref).strip()),
            None,
        )
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
            *[
                ref
                for item in bounded["operational_memory"]
                for ref in (item.get("evidence_refs") or ())
            ],
            *[
                ref
                for item in bounded["conversation_memory"]
                for ref in (item.get("evidence_refs") or ())
            ],
            *[
                ref
                for item in bounded["artifact_lineage_memory"]
                for ref in (item.get("evidence_refs") or ())
            ],
        ]))
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
        source = self.spec.task(from_task_id)
        target = self.spec.task(to_task_id)
        if from_task_id not in target.dependencies:
            raise PermissionError("Hermes handoff must follow CollaborationPlan dependency")
        refs = tuple(dict.fromkeys(str(ref).strip() for ref in evidence_refs if str(ref).strip()))
        known_refs = {
            row["evidence_ref"]
            for row in self._task_results.get(from_task_id, ())
        }
        if not refs or not set(refs).issubset(known_refs):
            raise PermissionError("Hermes handoff may reference only observed source-task evidence")
        body = (
            f"HANDOFF_FROM={from_task_id} HANDOFF_TO={to_task_id} "
            f"CAPABILITY={source.capability_id} EVIDENCE_REFS={json.dumps(refs)} "
            f"SUMMARY={str(summary).strip()[:1600]}"
        )
        comment_id = self.board.comment(
            self.task_mapping[to_task_id],
            author=f"hermes:{source.selected_agent_id or source.selected_skill_id or from_task_id}",
            body=body,
        )
        item = {
            "from_task_id": from_task_id,
            "to_task_id": to_task_id,
            "from_capability_id": source.capability_id,
            "to_capability_id": target.capability_id,
            "from_agent_id": source.selected_agent_id,
            "to_agent_id": target.selected_agent_id,
            "evidence_refs": list(refs),
            "summary": str(summary).strip(),
            "comment_id": comment_id,
        }
        self._handoffs.append(item)
        return item

    def request_human_input(self, *, task_id: str, question: str, run_id: int) -> dict[str, Any]:
        self.spec.task(task_id)
        normalized = str(question or "").strip()
        if not normalized:
            raise ValueError("human question is required")
        board_task_id = self.task_mapping[task_id]
        if not self.board.block(board_task_id, reason=normalized, run_id=run_id, kind="needs_input"):
            raise RuntimeError("Hermes task could not enter human-input block")
        dispatch = send_harness_message_to_human_group(
            authorization=self.parent_authorization,
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
        self.spec.task(task_id)
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
        self.spec.task(task_id)
        task = self.board.get_task(self.task_mapping[task_id])
        return {
            "mission_id": self.spec.mission_id,
            "task_id": task_id,
            "board_task_id": task["id"],
            "status": task["status"],
            "assignee": task.get("assignee"),
            "current_run_id": task.get("current_run_id"),
            "parents": list(self.spec.task(task_id).dependencies),
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
