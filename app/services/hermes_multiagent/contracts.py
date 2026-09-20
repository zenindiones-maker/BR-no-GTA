from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Mapping

from app.services.harness_collaboration_service import CollaborationPlan


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
    profile_roles: dict[str, str] = field(default_factory=dict)
    input_refs: tuple[str, ...] = ()
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
            profile_roles=dict(profile_roles or {}),
            input_refs=_string_tuple(input_refs, "input_refs", allow_empty=True),
        )

    def task(self, task_id: str):
        if task_id not in self.allowed_task_ids:
            raise PermissionError("Hermes task is outside the authorized mission scope")
        return next(task for task in self.collaboration_plan.tasks if task.task_id == task_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["collaboration_plan"] = self.collaboration_plan.to_dict()
        return data


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
