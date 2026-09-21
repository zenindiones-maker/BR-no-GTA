from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Callable

_ALLOWED_ACTIONS = {"RESEARCH", "EDITORIAL", "DEVELOPMENT", "EXECUTION", "DECISION"}
_ALLOWED_RISK_CLASSES = {
    "READ_ONLY",
    "LOW",
    "MEDIUM",
    "HIGH",
    "EXTERNAL_SIDE_EFFECT",
}
_TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")

class SemanticPlannerProviderFailure(RuntimeError):
    """Provider failure carrying sanitized Harness evidence for fail-closed profiling."""

    def __init__(self, code: str, evidence: dict[str, Any]) -> None:
        self.code = str(code or "provider_failed")
        self.evidence = dict(evidence or {})
        super().__init__(f"SEMANTIC_PLANNER_PROVIDER_FAILED:{self.code}")


def _sanitized_provider_failure_evidence(evidence: Any) -> dict[str, Any]:
    error = dict(getattr(evidence, "error", None) or {})
    performance = dict(getattr(evidence, "performance", None) or {})
    safe_performance_keys = {
        "prompt_bytes",
        "prompt_token_estimate",
        "requested_output_tokens",
        "num_ctx",
        "structured_json_mode",
        "timeout_seconds",
        "latency_seconds",
        "ollama_total_duration_seconds",
        "ollama_load_duration_seconds",
        "prompt_eval_duration_seconds",
        "eval_duration_seconds",
        "prompt_eval_tokens",
        "generation_tokens",
        "prompt_eval_tokens_per_second",
        "generation_tokens_per_second",
        "time_to_first_token_seconds",
    }
    safe_error_keys = {
        "code",
        "status_code",
        "retryable",
        "error_type",
        "failure_pattern",
    }
    return {
        "provider": getattr(evidence, "provider", None),
        "model": getattr(evidence, "model", None),
        "status": getattr(evidence, "status", None),
        "active": bool(getattr(evidence, "active", False)),
        "latency_seconds": getattr(evidence, "latency_seconds", None),
        "executor_binding": getattr(evidence, "executor_binding", None),
        "error": {
            key: error.get(key)
            for key in sorted(safe_error_keys)
            if error.get(key) is not None
        },
        "performance": {
            key: performance.get(key)
            for key in sorted(safe_performance_keys)
            if performance.get(key) is not None
        },
        "evidence_refs": list(getattr(evidence, "evidence_refs", ()) or ()),
        "authority": getattr(evidence, "authority", None),
        "planner_authority": "NONE",
    }



def _required_text(value: Any, field: str, *, max_len: int = 2400) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds bounded length")
    return text


def _string_tuple(value: Any, field: str, *, limit: int, max_item_len: int = 1200) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > max_item_len:
            raise ValueError(f"{field} contains oversized item")
        if text not in seen:
            result.append(text)
            seen.add(text)
        if len(result) > limit:
            raise ValueError(f"{field} exceeds bounded item count")
    return tuple(result)


@dataclass(frozen=True)
class MissionTaskProposal:
    task_id: str
    objective: str
    task_class: str
    required_capability_description: str
    candidate_capability_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    expected_output: str
    acceptance_criteria: tuple[str, ...]
    risk_side_effect_class: str
    action: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "MissionTaskProposal":
        if not isinstance(value, dict):
            raise ValueError("semantic task proposal must be an object")
        forbidden = {
            "executor",
            "executor_binding",
            "selected_executor",
            "selected_agent_id",
            "authorization",
            "authorization_id",
            "policy_override",
            "publication_authority",
        }
        leaked = sorted(forbidden.intersection(value))
        if leaked:
            raise PermissionError(
                "semantic planner attempted authority-bearing fields: " + ",".join(leaked)
            )
        task_id = _required_text(value.get("task_id"), "task_id", max_len=80)
        if not _TASK_ID_RE.fullmatch(task_id):
            raise ValueError(f"invalid task_id: {task_id}")
        action = _required_text(value.get("action"), "action", max_len=32).upper()
        if action not in _ALLOWED_ACTIONS:
            raise ValueError(f"unsupported proposed action: {action}")
        risk = _required_text(
            value.get("risk_side_effect_class") or "READ_ONLY",
            "risk_side_effect_class",
            max_len=40,
        ).upper()
        if risk not in _ALLOWED_RISK_CLASSES:
            raise ValueError(f"unsupported risk_side_effect_class: {risk}")
        dependencies = _string_tuple(value.get("dependencies"), "dependencies", limit=12, max_item_len=80)
        if task_id in dependencies:
            raise ValueError("semantic task cannot depend on itself")
        criteria = _string_tuple(
            value.get("acceptance_criteria"),
            "acceptance_criteria",
            limit=2,
            max_item_len=240,
        )
        if not criteria:
            raise ValueError(f"task {task_id} requires acceptance_criteria")
        return cls(
            task_id=task_id,
            objective=_required_text(
                value.get("objective"),
                "objective",
                max_len=220,
            ),
            task_class=_required_text(
                value.get("task_class"),
                "task_class",
                max_len=96,
            ),
            required_capability_description=_required_text(
                value.get("required_capability_description"),
                "required_capability_description",
                max_len=180,
            ),
            candidate_capability_ids=_string_tuple(
                value.get("candidate_capability_ids"),
                "candidate_capability_ids",
                limit=3,
                max_item_len=160,
            ),
            dependencies=dependencies,
            expected_output=_required_text(
                value.get("expected_output"),
                "expected_output",
                max_len=120,
            ),
            acceptance_criteria=criteria,
            risk_side_effect_class=risk,
            action=action,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MissionPlanProposal:
    interpreted_goal: str
    assumptions: tuple[str, ...]
    required_outcomes: tuple[str, ...]
    tasks: tuple[MissionTaskProposal, ...]
    rationale: str
    context_usage_notes: tuple[str, ...]
    uncertainty: float
    needs_human_clarification: bool
    clarification_question: str | None = None
    memory_strategy_notes: tuple[str, ...] = ()
    reused_artifact_refs: tuple[str, ...] = ()
    avoided_bad_paths: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any], *, max_tasks: int) -> "MissionPlanProposal":
        if not isinstance(value, dict):
            raise ValueError("semantic planner output must be a JSON object")
        authority_fields = {
            "authority",
            "authorization",
            "authorization_id",
            "selected_executor_binding",
            "routing_authority",
            "publication_authority",
            "promotion_decision",
        }
        leaked = sorted(authority_fields.intersection(value))
        if leaked:
            raise PermissionError(
                "semantic planner attempted authority-bearing proposal fields: " + ",".join(leaked)
            )
        raw_tasks = value.get("tasks")
        if not isinstance(raw_tasks, list):
            raise ValueError("semantic planner tasks must be a list")
        if not raw_tasks or len(raw_tasks) > max_tasks:
            raise ValueError("semantic planner task count is outside resource bounds")
        tasks = tuple(MissionTaskProposal.from_mapping(item) for item in raw_tasks)
        by_id = {task.task_id: task for task in tasks}
        if len(by_id) != len(tasks):
            raise ValueError("semantic planner task_id values must be unique")
        known = set(by_id)
        for task in tasks:
            missing = set(task.dependencies) - known
            if missing:
                raise ValueError(
                    f"semantic planner unknown dependencies for {task.task_id}: {sorted(missing)}"
                )
        remaining = set(known)
        resolved: set[str] = set()
        while remaining:
            ready = {
                task_id
                for task_id in remaining
                if set(by_id[task_id].dependencies) <= resolved
            }
            if not ready:
                raise ValueError("semantic planner produced dependency cycle")
            resolved.update(ready)
            remaining.difference_update(ready)
        try:
            uncertainty = float(value.get("uncertainty", 0.5))
        except (TypeError, ValueError) as exc:
            raise ValueError("uncertainty must be numeric") from exc
        if uncertainty < 0.0 or uncertainty > 1.0:
            raise ValueError("uncertainty must be within 0..1")
        needs_clarification = bool(value.get("needs_human_clarification", False))
        clarification = str(value.get("clarification_question") or "").strip() or None
        if needs_clarification and not clarification:
            raise ValueError("clarification_question is required when clarification is needed")
        required_outcomes = _string_tuple(
            value.get("required_outcomes"),
            "required_outcomes",
            limit=4,
            max_item_len=240,
        )
        if not required_outcomes:
            raise ValueError("semantic planner requires at least one required_outcome")
        return cls(
            interpreted_goal=_required_text(
                value.get("interpreted_goal"),
                "interpreted_goal",
                max_len=240,
            ),
            assumptions=_string_tuple(
                value.get("assumptions"),
                "assumptions",
                limit=2,
                max_item_len=240,
            ),
            required_outcomes=required_outcomes,
            tasks=tasks,
            rationale=_required_text(
                value.get("rationale"),
                "rationale",
                max_len=240,
            ),
            context_usage_notes=_string_tuple(
                value.get("context_usage_notes"),
                "context_usage_notes",
                limit=3,
                max_item_len=240,
            ),
            uncertainty=uncertainty,
            needs_human_clarification=needs_clarification,
            clarification_question=clarification,
            memory_strategy_notes=_string_tuple(
                value.get("memory_strategy_notes"),
                "memory_strategy_notes",
                limit=3,
                max_item_len=240,
            ),
            reused_artifact_refs=_string_tuple(
                value.get("reused_artifact_refs"),
                "reused_artifact_refs",
                limit=3,
                max_item_len=200,
            ),
            avoided_bad_paths=_string_tuple(
                value.get("avoided_bad_paths"),
                "avoided_bad_paths",
                limit=3,
                max_item_len=200,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interpreted_goal": self.interpreted_goal,
            "assumptions": list(self.assumptions),
            "required_outcomes": list(self.required_outcomes),
            "tasks": [task.to_dict() for task in self.tasks],
            "rationale": self.rationale,
            "context_usage_notes": list(self.context_usage_notes),
            "uncertainty": self.uncertainty,
            "needs_human_clarification": self.needs_human_clarification,
            "clarification_question": self.clarification_question,
            "memory_strategy_notes": list(self.memory_strategy_notes),
            "reused_artifact_refs": list(self.reused_artifact_refs),
            "avoided_bad_paths": list(self.avoided_bad_paths),
        }


@dataclass(frozen=True)
class SemanticPlannerResult:
    proposal: MissionPlanProposal
    provider_evidence: dict[str, Any]
    prompt_sha256: str
    provider_call_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.to_dict(),
            "provider_evidence": dict(self.provider_evidence),
            "prompt_sha256": self.prompt_sha256,
            "provider_call_count": self.provider_call_count,
        }


def _json_object(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("semantic planner did not return a JSON object")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("semantic planner JSON root must be an object")
    return parsed


def mission_plan_json_schema(*, max_tasks: int) -> dict[str, Any]:
    max_tasks = max(1, min(int(max_tasks), 12))
    string_240 = {"type": "string", "minLength": 1, "maxLength": 240}
    string_200 = {"type": "string", "minLength": 1, "maxLength": 200}
    task_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "task_id",
            "objective",
            "task_class",
            "required_capability_description",
            "candidate_capability_ids",
            "dependencies",
            "expected_output",
            "acceptance_criteria",
            "risk_side_effect_class",
            "action",
        ],
        "properties": {
            "task_id": {
                "type": "string",
                "pattern": "^[a-z0-9][a-z0-9._-]{0,79}$",
            },
            "objective": {"type": "string", "minLength": 1, "maxLength": 220},
            "task_class": {"type": "string", "minLength": 1, "maxLength": 96},
            "required_capability_description": {
                "type": "string",
                "minLength": 1,
                "maxLength": 180,
            },
            "candidate_capability_ids": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string", "minLength": 1, "maxLength": 160},
            },
            "dependencies": {
                "type": "array",
                "maxItems": 12,
                "items": {"type": "string", "minLength": 1, "maxLength": 80},
            },
            "expected_output": {
                "type": "string",
                "minLength": 1,
                "maxLength": 120,
            },
            "acceptance_criteria": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": string_240,
            },
            "risk_side_effect_class": {
                "type": "string",
                "enum": sorted(_ALLOWED_RISK_CLASSES),
            },
            "action": {
                "type": "string",
                "enum": sorted(_ALLOWED_ACTIONS),
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "interpreted_goal",
            "assumptions",
            "required_outcomes",
            "tasks",
            "rationale",
            "context_usage_notes",
            "uncertainty",
            "needs_human_clarification",
            "clarification_question",
            "memory_strategy_notes",
            "reused_artifact_refs",
            "avoided_bad_paths",
        ],
        "properties": {
            "interpreted_goal": string_240,
            "assumptions": {
                "type": "array",
                "maxItems": 2,
                "items": string_240,
            },
            "required_outcomes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": string_240,
            },
            "tasks": {
                "type": "array",
                "minItems": 1,
                "maxItems": max_tasks,
                "items": task_schema,
            },
            "rationale": string_240,
            "context_usage_notes": {
                "type": "array",
                "maxItems": 3,
                "items": string_240,
            },
            "uncertainty": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "needs_human_clarification": {"type": "boolean"},
            "clarification_question": {
                "anyOf": [
                    {"type": "null"},
                    {"type": "string", "minLength": 1, "maxLength": 240},
                ]
            },
            "memory_strategy_notes": {
                "type": "array",
                "maxItems": 3,
                "items": string_240,
            },
            "reused_artifact_refs": {
                "type": "array",
                "maxItems": 3,
                "items": string_200,
            },
            "avoided_bad_paths": {
                "type": "array",
                "maxItems": 3,
                "items": string_200,
            },
        },
    }


def _prompt_payload(
    context: dict[str, Any],
    validation_feedback: tuple[str, ...],
) -> dict[str, Any]:
    payload = {
        "human_goal": context["human_goal"],
        "subject": context.get("subject"),
        "canonical_state": context.get("canonical_state") or {},
        "conversation_state": context.get("conversation_state") or {},
        "memory": context.get("bounded_memory_context") or {},
        "history": context.get("recent_execution_history") or [],
        "failure_memory": context.get("relevant_failure_memories") or [],
        "human_decisions": context.get("human_feedback_decisions") or [],
        "provider_health": context.get("provider_health") or {},
        "capabilities": context.get("registry_summary") or [],
        "competence": context.get("competence_evidence") or [],
        "resource_bounds": context.get("resource_bounds") or {},
        "known_bad_paths": context.get("known_bad_paths") or [],
        "validation_feedback": list(validation_feedback),
    }
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }

def build_semantic_planner_prompt(
    context: dict[str, Any],
    *,
    validation_feedback: tuple[str, ...] = (),
) -> str:
    max_tasks = int(
        (context.get("resource_bounds") or {}).get("max_tasks_per_mission")
        or 8
    )
    contract = {
        "assumptions": "max2",
        "required_outcomes": "max4",
        "tasks": "minimum sufficient; max" + str(max_tasks),
        "task": {
            "candidate_capability_ids": "max3 exact Registry IDs; [] if unsure",
            "acceptance_criteria": "1-2 observable criteria",
            "dependencies": "task_id list",
        },
        "rationale": "1 short sentence",
        "context_usage_notes": "max3",
        "memory_strategy_notes": "max3",
        "reused_artifact_refs": "max3",
        "avoided_bad_paths": "max3",
    }
    instructions = (
        "You propose a MissionPlan only; authority=NONE. Return one strict JSON "
        "object using the required MissionPlan fields. Use the minimum sufficient "
        "dynamic DAG, observe before mutation when cause is unknown, reuse relevant "
        "memory/checkpoints, account for competence and known failures, and require "
        "independent validation for risky/mutating work. Never invent capability "
        "IDs, choose executor bindings, authorize, publish, promote, or mutate policy. "
        "Do not repeat the human goal or explain known capability IDs. Keep every "
        "string concise. Ask for clarification only when a missing fact prevents a "
        "safe feasible plan."
    )
    return "\n".join(
        [
            instructions,
            "OUTPUT_CONTRACT="
            + json.dumps(
                contract,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "CONTEXT="
            + json.dumps(
                _prompt_payload(context, validation_feedback),
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ),
        ]
    )

def _live_inference(prompt: str, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from app.services.harness_ai_provider_service import execute_harness_ai_generation
    from app.services.harness_authorization_service import (
        consume_harness_authorization,
        issue_harness_authorization,
    )
    from app.services.harness_routing_policy_service import (
        HarnessRoutingRequest,
        route_harness_request,
    )

    health = dict(context.get("provider_health") or {})
    providers = tuple(str(item) for item in health.get("eligible_zero_cost_provider_ids") or ())
    if not providers:
        raise RuntimeError("SEMANTIC_REASONING_PROVIDER_UNAVAILABLE")

    routing = None
    selected_provider = None
    last_error: Exception | None = None
    for provider_id in providers:
        try:
            decision = route_harness_request(
                HarnessRoutingRequest(
                    intent="semantic mission planning proposal only",
                    authorized_action="DECISION",
                    domain="ai",
                    goal_id=str(context.get("goal_id") or "semantic-plan"),
                    task_class="semantic-mission-planning",
                    required_capability_id="ai.reasoning.text",
                    provider_required=True,
                    preferred_providers=(provider_id,),
                    fallback_allowed=False,
                    zero_cost_operation=True,
                    learning_required=True,
                )
            )
            routing = decision
            selected_provider = decision.selected_provider
            if selected_provider:
                break
        except Exception as exc:
            last_error = exc
    if routing is None or not selected_provider:
        if last_error is not None:
            raise RuntimeError("SEMANTIC_REASONING_PROVIDER_UNAVAILABLE") from last_error
        raise RuntimeError("SEMANTIC_REASONING_PROVIDER_UNAVAILABLE")

    prompt_sha = sha256(prompt.encode("utf-8")).hexdigest()
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"provider:{selected_provider}",
        harness_decision_id=routing.routing_id,
        lineage={
            "goal_id": str(context.get("goal_id") or "semantic-plan"),
            "semantic_planner_role": "PROPOSAL_ONLY",
            "routing_id": routing.routing_id,
            "selected_provider": selected_provider,
            "prompt_sha256": prompt_sha,
            "authority": "DEEPSEEK_HARNESS",
            "planner_authority": "NONE",
        },
    )
    try:
        evidence = execute_harness_ai_generation(
            prompt=prompt,
            authorization=authorization,
            routing_decision=routing,
        )
    finally:
        consume_harness_authorization(authorization)

    if evidence.status != "EXECUTED" or not evidence.active:
        error = dict(evidence.error or {})
        code = str(error.get("code") or "provider_failed")
        raise SemanticPlannerProviderFailure(
            code,
            _sanitized_provider_failure_evidence(evidence),
        )
    result = dict(evidence.result or {})
    response_text = str(result.get("text") or "").strip()
    if not response_text:
        raise SemanticPlannerProviderFailure(
            "empty_response",
            _sanitized_provider_failure_evidence(evidence),
        )
    return response_text, {
        "provider": evidence.provider,
        "model": evidence.model,
        "routing_id": routing.routing_id,
        "authorization_id": evidence.authorization_id,
        "executor_binding": evidence.executor_binding,
        "latency_seconds": evidence.latency_seconds,
        "usage": dict((result.get("usage") or {})),
        "performance": dict(evidence.performance or {}),
        "evidence_refs": list(evidence.evidence_refs),
        "status": evidence.status,
        "authority": evidence.authority,
        "planner_authority": "NONE",
    }


def propose_semantic_mission_plan(
    context: dict[str, Any],
    *,
    inference: Callable[[str, dict[str, Any]], str | dict[str, Any]] | None = None,
    validation_feedback: tuple[str, ...] = (),
) -> SemanticPlannerResult:
    resources = dict(context.get("resource_bounds") or {})
    max_tasks = int(resources.get("max_tasks_per_mission") or 8)
    if max_tasks < 1 or max_tasks > 12:
        raise ValueError("semantic planner max_tasks is outside Harness resource governance")
    prompt = build_semantic_planner_prompt(
        context,
        validation_feedback=validation_feedback,
    )
    prompt_sha = sha256(prompt.encode("utf-8")).hexdigest()
    if inference is None:
        raw, provider_evidence = _live_inference(prompt, context)
        provider_call_count = 1
    else:
        raw = inference(prompt, context)
        provider_evidence = {
            "provider": "INJECTED_INFERENCE",
            "status": "EXECUTED",
            "authority": "DEEPSEEK_HARNESS",
            "planner_authority": "NONE",
        }
        provider_call_count = 1
    if isinstance(raw, dict):
        mapping = raw
    else:
        mapping = _json_object(str(raw))
    proposal = MissionPlanProposal.from_mapping(mapping, max_tasks=max_tasks)
    return SemanticPlannerResult(
        proposal=proposal,
        provider_evidence=provider_evidence,
        prompt_sha256=prompt_sha,
        provider_call_count=provider_call_count,
    )
