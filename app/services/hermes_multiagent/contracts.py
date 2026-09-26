from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Mapping

from app.services.harness_collaboration_service import CollaborationPlan, TaskEnvelope


HERMES_RUNTIME_CAPABILITY_ID = "collaboration.hermes.execute"
HERMES_AUTHORITY = "DELEGATED_ONLY"

MANDATORY_FORBIDDEN_ACTIONS = frozenset({
    "push",
    "merge",
    "canonical_branch_write",
    "policy_mutation",
    "authority_mutation",
    "secret_access",
    "credential_access",
    "youtube_publish_public",
    "external_paid_action",
})

HERMES_COORDINATION_TOOLS = (
    "kanban_show",
    "kanban_complete",
    "kanban_request_review",
    "kanban_request_changes",
    "kanban_block",
    "kanban_heartbeat",
    "kanban_comment",
    "kanban_create",
    "kanban_link",
    "kanban_unblock",
    "br_harness_status",
    "br_harness_capability_request",
    "br_harness_submit_evidence",
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _string_tuple(value: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    items = tuple(dict.fromkeys(
        str(item).strip()
        for item in (value or ())
        if str(item).strip()
    ))
    if not items and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    return items


def _iso_timestamp(value: Any, field_name: str) -> str:
    text = _required(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _scope_subset(child: tuple[str, ...], parent: tuple[str, ...]) -> bool:
    if not child:
        return True
    if not parent:
        return False
    normalized_parent = tuple(str(item).strip("/").replace("\\", "/") for item in parent)
    for raw in child:
        value = str(raw).strip("/").replace("\\", "/")
        if not any(
            value == root or value.startswith(root + "/")
            for root in normalized_parent
            if root
        ):
            return False
    return True


def _objective_within_parent(child: str, parent: str) -> bool:
    token_re = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.IGNORECASE)
    child_tokens = {item.casefold() for item in token_re.findall(str(child or ""))}
    parent_tokens = {item.casefold() for item in token_re.findall(str(parent or ""))}
    generic = {
        "task", "work", "execute", "analyze", "analysis", "system",
        "mission", "resultado", "result", "inspect", "check",
    }
    child_tokens -= generic
    parent_tokens -= generic
    return bool(child_tokens and parent_tokens and child_tokens & parent_tokens)


@dataclass(frozen=True)
class HermesProfileIdentity:
    profile_instance_id: str
    profile_role: str
    mission_id: str
    plan_task_id: str
    worker_instance_id: str
    description: str
    profile_home: str
    worker_build_id: str
    capability_ids: tuple[str, ...]
    attempt_id: str | None = None
    schema: str = "HermesProfileIdentity/v1"
    authority: str = HERMES_AUTHORITY
    publication_authority: str = "NONE"

    def __post_init__(self) -> None:
        for name in ("profile_instance_id","profile_role","mission_id","plan_task_id","worker_instance_id","description","profile_home","worker_build_id"):
            _required(getattr(self,name),name)
        if not self.capability_ids:
            raise ValueError("capability_ids must not be empty")
        if self.authority != HERMES_AUTHORITY or self.publication_authority != "NONE":
            raise PermissionError("Hermes profile identity cannot gain mission/publication authority")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HermesRuntimeProfile:
    profile_name: str
    task_id: str
    runtime_role: str
    capability_id: str
    domain: str
    action: str
    canonical_agent_id: str | None
    canonical_skill_id: str | None
    executor_binding: str
    input_contract: str
    output_contract: str
    evidence_contract: str
    evidence_expectations: tuple[str, ...]
    allowed_tools: tuple[str, ...] = HERMES_COORDINATION_TOOLS
    authority: str = HERMES_AUTHORITY
    memory_write: str = "FORBIDDEN"
    publication_authority: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TypedHandoff:
    from_task_id: str
    to_task_id: str
    evidence_refs: tuple[str, ...]
    result_ref: str
    output_contract: str
    summary: str
    acceptance_state: str
    artifact_lineage: dict[str, Any]
    producer_capability_id: str
    producer_agent_id: str | None
    producer_skill_id: str | None
    producer_version: str
    observed_at: str

    def __post_init__(self) -> None:
        if not self.from_task_id or not self.to_task_id:
            raise ValueError("TypedHandoff task ids are required")
        if not self.evidence_refs:
            raise ValueError("TypedHandoff evidence_refs are required")
        if not self.result_ref:
            raise ValueError("TypedHandoff result_ref is required")
        if len(self.summary.encode("utf-8")) > 4096:
            raise ValueError("TypedHandoff summary exceeds bounded size")
        _iso_timestamp(self.observed_at, "observed_at")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HermesMissionExecutionSpec:
    mission_id: str
    goal_id: str
    harness_decision_id: str
    authorization_id: str
    base_sha: str
    collaboration_plan: CollaborationPlan
    allowed_task_ids: tuple[str, ...]
    allowed_capability_ids: tuple[str, ...]
    allowed_agent_ids: tuple[str, ...]
    budgets: dict[str, Any]
    evidence_requirements: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    expires_at: str
    authorized_read_scope: tuple[str, ...] = ()
    authorized_write_scope: tuple[str, ...] = ()
    allowed_side_effects: tuple[str, ...] = ()
    human_gates: tuple[str, ...] = ()
    max_child_depth: int = 1
    max_child_tasks: int = 8
    profile_roles: dict[str, str] = field(default_factory=dict)
    input_refs: tuple[str, ...] = ()
    allowed_child_capability_ids: tuple[str, ...] = ()
    authority: str = HERMES_AUTHORITY

    def __post_init__(self) -> None:
        for name in ("mission_id", "goal_id", "harness_decision_id", "authorization_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        sha = str(self.base_sha or "").strip().lower()
        if not _SHA_RE.fullmatch(sha):
            raise ValueError("base_sha must be an exact 40-character git SHA")
        object.__setattr__(self, "base_sha", sha)
        object.__setattr__(self, "expires_at", _iso_timestamp(self.expires_at, "expires_at"))
        if self.collaboration_plan.mission_id != self.mission_id:
            raise ValueError("CollaborationPlan mission_id mismatch")
        if self.collaboration_plan.goal_id != self.goal_id:
            raise ValueError("CollaborationPlan goal_id mismatch")
        if self.collaboration_plan.authority != "DEEPSEEK_HARNESS":
            raise PermissionError("CollaborationPlan escaped DeepSeek Harness authority")

        plan_task_ids = {task.task_id for task in self.collaboration_plan.tasks}
        allowed_tasks = set(self.allowed_task_ids)
        if not allowed_tasks or not allowed_tasks <= plan_task_ids:
            raise PermissionError("allowed_task_ids must be a non-empty subset of CollaborationPlan tasks")
        plan_capabilities = {
            task.capability_id for task in self.collaboration_plan.tasks
            if task.task_id in allowed_tasks
        }
        if set(self.allowed_capability_ids) != plan_capabilities:
            raise PermissionError("allowed_capability_ids must exactly match routed mission tasks")

        plan_agents = {
            task.selected_agent_id
            for task in self.collaboration_plan.tasks
            if task.task_id in allowed_tasks and task.selected_agent_id
        }
        supplied_agents = set(self.allowed_agent_ids)
        if not supplied_agents.issubset(plan_agents):
            raise PermissionError("allowed_agent_ids may only contain Harness-selected agents")

        forbidden = {item.strip() for item in self.forbidden_actions if item.strip()}
        missing = MANDATORY_FORBIDDEN_ACTIONS - forbidden
        if missing:
            raise PermissionError(f"Hermes mission omitted mandatory forbidden actions: {sorted(missing)}")
        if not isinstance(self.budgets, dict):
            raise ValueError("budgets must be a mapping")
        if float(self.budgets.get("cost", 0.0)) < 0:
            raise ValueError("cost budget cannot be negative")
        if int(self.budgets.get("retry_count", 0)) < 0:
            raise ValueError("retry_count budget cannot be negative")
        if int(self.budgets.get("max_parallelism", 1)) < 1:
            raise ValueError("max_parallelism must be positive")
        if self.max_child_depth < 0 or self.max_child_depth > 4:
            raise ValueError("max_child_depth must be in [0, 4]")
        if self.max_child_tasks < 0 or self.max_child_tasks > 64:
            raise ValueError("max_child_tasks must be in [0, 64]")

        plan_tasks = [
            task for task in self.collaboration_plan.tasks
            if task.task_id in allowed_tasks
        ]
        plan_read_scope = tuple(dict.fromkeys(
            path for task in plan_tasks for path in task.read_scope
        ))
        plan_write_scope = tuple(dict.fromkeys(
            path for task in plan_tasks for path in task.write_scope
        ))
        plan_side_effects = tuple(dict.fromkeys(
            effect for task in plan_tasks for effect in task.allowed_side_effects
        ))
        if not self.authorized_read_scope:
            object.__setattr__(self, "authorized_read_scope", plan_read_scope)
        elif not _scope_subset(plan_read_scope, self.authorized_read_scope):
            raise PermissionError("DelegationEnvelope read scope excludes planned task scope")
        if not self.authorized_write_scope:
            object.__setattr__(self, "authorized_write_scope", plan_write_scope)
        elif not _scope_subset(plan_write_scope, self.authorized_write_scope):
            raise PermissionError("DelegationEnvelope write scope excludes planned task scope")
        if not self.allowed_side_effects:
            object.__setattr__(self, "allowed_side_effects", plan_side_effects)
        elif not set(plan_side_effects) <= set(self.allowed_side_effects):
            raise PermissionError("DelegationEnvelope side effects exclude planned task effects")

        child_caps = tuple(dict.fromkeys(
            str(item).strip()
            for item in self.allowed_child_capability_ids
            if str(item).strip()
        ))
        object.__setattr__(
            self,
            "allowed_child_capability_ids",
            child_caps,
        )

        unknown_role_tasks = set(self.profile_roles) - allowed_tasks
        if unknown_role_tasks:
            raise PermissionError(f"profile role assigned outside allowed task scope: {sorted(unknown_role_tasks)}")

    @classmethod
    def from_plan(
        cls,
        *,
        collaboration_plan: CollaborationPlan,
        harness_decision_id: str,
        authorization_id: str,
        base_sha: str,
        expires_at: str,
        budgets: Mapping[str, Any] | None = None,
        evidence_requirements: tuple[str, ...] | list[str] = (),
        forbidden_actions: tuple[str, ...] | list[str] = (),
        profile_roles: Mapping[str, str] | None = None,
        input_refs: tuple[str, ...] | list[str] = (),
        human_gates: tuple[str, ...] | list[str] = (),
        max_child_depth: int = 1,
        max_child_tasks: int | None = None,
        allowed_child_capability_ids: tuple[str, ...] | list[str] = (),
    ) -> "HermesMissionExecutionSpec":
        task_ids = tuple(task.task_id for task in collaboration_plan.tasks)
        capability_ids = tuple(dict.fromkeys(task.capability_id for task in collaboration_plan.tasks))
        agent_ids = tuple(dict.fromkeys(
            task.selected_agent_id
            for task in collaboration_plan.tasks
            if task.selected_agent_id
        ))
        forbidden = tuple(sorted(set(forbidden_actions) | MANDATORY_FORBIDDEN_ACTIONS))
        return cls(
            mission_id=collaboration_plan.mission_id,
            goal_id=collaboration_plan.goal_id,
            harness_decision_id=harness_decision_id,
            authorization_id=authorization_id,
            base_sha=base_sha,
            collaboration_plan=collaboration_plan,
            allowed_task_ids=task_ids,
            allowed_capability_ids=capability_ids,
            allowed_agent_ids=agent_ids,
            budgets=dict(budgets or {
                "max_parallelism": max(1, max((len(level) for level in collaboration_plan.execution_levels), default=1)),
                "retry_count": 1,
                "time_seconds": 900,
                "cost": 0.0,
            }),
            evidence_requirements=_string_tuple(
                evidence_requirements or ("Hermes board export", "Harness authorization lineage"),
                "evidence_requirements",
            ),
            forbidden_actions=forbidden,
            expires_at=expires_at,
            authorized_read_scope=tuple(dict.fromkeys(
                path for task in collaboration_plan.tasks for path in task.read_scope
            )),
            authorized_write_scope=tuple(dict.fromkeys(
                path for task in collaboration_plan.tasks for path in task.write_scope
            )),
            allowed_side_effects=tuple(dict.fromkeys(
                effect
                for task in collaboration_plan.tasks
                for effect in task.allowed_side_effects
            )),
            human_gates=_string_tuple(
                human_gates,
                "human_gates",
                allow_empty=True,
            ),
            max_child_depth=int(max_child_depth),
            max_child_tasks=(
                int(max_child_tasks)
                if max_child_tasks is not None
                else max(4, len(collaboration_plan.tasks) * 3)
            ),
            profile_roles=dict(profile_roles or {}),
            input_refs=_string_tuple(input_refs, "input_refs", allow_empty=True),
            allowed_child_capability_ids=_string_tuple(
                allowed_child_capability_ids,
                "allowed_child_capability_ids",
                allow_empty=True,
            ),
        )

    def task(self, task_id: str):
        if task_id not in self.allowed_task_ids:
            raise PermissionError("Hermes task is outside the authorized mission scope")
        return next(
            task for task in self.collaboration_plan.tasks
            if task.task_id == task_id
        )

    def validate_child_task(
        self,
        *,
        parent_task_id: str,
        child: Mapping[str, Any],
        depth: int,
        existing_child_count: int,
        parent_envelope: Any | None = None,
    ) -> TaskEnvelope:
        parent = parent_envelope if parent_envelope is not None else self.task(parent_task_id)
        if str(getattr(parent, "mission_id", self.mission_id)) not in {
            "UNBOUND",
            self.mission_id,
        }:
            raise PermissionError("Hermes child parent escaped mission identity")
        if depth < 1 or depth > self.max_child_depth:
            raise PermissionError("Hermes child task depth exceeds DelegationEnvelope")
        if existing_child_count >= self.max_child_tasks:
            raise PermissionError("Hermes child task count exceeds DelegationEnvelope")
        capability_id = _required(child.get("capability_id"), "child.capability_id")
        if capability_id not in {
            *self.allowed_capability_ids,
            *self.allowed_child_capability_ids,
        }:
            raise PermissionError("Hermes child capability is outside allowlist")
        action = _required(
            child.get("authorized_action") or child.get("action"),
            "child.authorized_action",
        ).upper()
        if action != parent.action:
            raise PermissionError("Hermes child task attempted authority expansion")
        objective = _required(child.get("objective"), "child.objective")
        if not _objective_within_parent(objective, parent.objective):
            raise PermissionError("Hermes child objective escaped parent objective")
        read_scope = _string_tuple(
            child.get("read_scope"),
            "child.read_scope",
            allow_empty=True,
        )
        write_scope = _string_tuple(
            child.get("write_scope"),
            "child.write_scope",
            allow_empty=True,
        )
        if not _scope_subset(read_scope, parent.read_scope):
            raise PermissionError("Hermes child read scope expands parent")
        if not _scope_subset(write_scope, parent.write_scope):
            raise PermissionError("Hermes child write scope expands parent")
        if not _scope_subset(read_scope, self.authorized_read_scope):
            raise PermissionError("Hermes child read scope expands mission")
        if not _scope_subset(write_scope, self.authorized_write_scope):
            raise PermissionError("Hermes child write scope expands mission")
        side_effects = _string_tuple(
            child.get("allowed_side_effects"),
            "child.allowed_side_effects",
            allow_empty=True,
        )
        if not set(side_effects) <= set(parent.allowed_side_effects):
            raise PermissionError("Hermes child side effects expand parent")
        if not set(side_effects) <= set(self.allowed_side_effects):
            raise PermissionError("Hermes child side effects expand mission")
        if set(side_effects) & set(parent.forbidden_side_effects):
            raise PermissionError("Hermes child requested forbidden side effect")

        child_time = int(child.get("time_budget_seconds") or parent.time_budget_seconds)
        child_cost = float(
            child.get("cost_budget")
            if child.get("cost_budget") is not None
            else parent.cost_budget
        )
        child_context = int(
            child.get("context_budget_bytes") or parent.context_budget_bytes
        )
        child_tools = int(child.get("tool_budget") or parent.tool_budget)
        child_retry = int(
            child.get("retry_budget")
            if child.get("retry_budget") is not None
            else parent.retry_budget
        )
        if child_time > parent.time_budget_seconds:
            raise PermissionError("Hermes child time budget expands parent")
        if child_cost > parent.cost_budget:
            raise PermissionError("Hermes child cost budget expands parent")
        if child_context > parent.context_budget_bytes:
            raise PermissionError("Hermes child context budget expands parent")
        if child_tools > parent.tool_budget:
            raise PermissionError("Hermes child tool budget expands parent")
        if child_retry > parent.retry_budget:
            raise PermissionError("Hermes child retry budget expands parent")

        return TaskEnvelope.from_mapping({
            **dict(child),
            "task_id": _required(child.get("task_id"), "child.task_id"),
            "capability_id": capability_id,
            "action": action,
            "objective": objective,
            "task_class": str(
                child.get("task_class") or parent.task_class
            ),
            "dependencies": tuple(child.get("dependencies") or ()),
            "read_scope": read_scope,
            "write_scope": write_scope,
            "allowed_tools": tuple(
                item for item in (child.get("allowed_tools") or parent.allowed_tools)
                if item in parent.allowed_tools
            ),
            "allowed_side_effects": side_effects,
            "forbidden_side_effects": parent.forbidden_side_effects,
            "time_budget_seconds": child_time,
            "cost_budget": child_cost,
            "context_budget_bytes": child_context,
            "tool_budget": child_tools,
            "retry_budget": child_retry,
            "evidence_contract": str(
                child.get("evidence_contract") or parent.evidence_contract
            ),
            "review_policy": str(
                child.get("review_policy") or parent.review_policy
            ),
            "risk_side_effect_class": str(
                child.get("risk_side_effect_class")
                or parent.risk_side_effect_class
            ),
            "human_gate_policy": parent.human_gate_policy,
            "mission_id": self.mission_id,
            "goal_id": self.goal_id,
        })

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["collaboration_plan"] = self.collaboration_plan.to_dict()
        return data


# Canonical name requested by the control plane; no second envelope exists.
DelegationEnvelope = HermesMissionExecutionSpec


@dataclass(frozen=True)
class HermesMissionExecutionResult:
    mission_id: str
    board_id: str
    run_id: str
    status: str
    workers: tuple[dict[str, Any], ...]
    tasks: tuple[dict[str, Any], ...]
    comments_handoffs: tuple[dict[str, Any], ...]
    retries: tuple[dict[str, Any], ...]
    blocks: tuple[dict[str, Any], ...]
    reviews: tuple[dict[str, Any], ...]
    artifacts: tuple[str, ...]
    elapsed_seconds: float
    cost: float
    evidence_refs: tuple[str, ...]
    final_task_statuses: dict[str, str]
    canonical_result_refs: tuple[str, ...]
    harness_episode_ids: tuple[str, ...] = ()
    authority: str = HERMES_AUTHORITY
    publication_authority: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
