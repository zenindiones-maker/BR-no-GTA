from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any, Mapping


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")

PROACTIVE_READ_ONLY_ACTIONS = frozenset({
    "READ",
    "SEARCH",
    "INSPECT",
    "COMPARE",
    "RETRIEVE",
    "SUMMARIZE",
    "CREATE_PRIVATE_CANDIDATE_NOTE",
    "CREATE_IMPROVEMENT_OPPORTUNITY",
    "CREATE_EDITORIAL_OPPORTUNITY_CANDIDATE",
})

PROACTIVE_FORBIDDEN_SIDE_EFFECTS = frozenset({
    "PUSH",
    "MERGE",
    "PUBLISH",
    "SEND_EXTERNAL_MESSAGE",
    "MODIFY_GITHUB",
    "MODIFY_YOUTUBE",
    "DEPLOY",
    "EDIT_EXTERNAL_SYSTEM",
    "CHANGE_PERMISSIONS",
    "ROTATE_CREDENTIALS",
    "YOUTUBE_PUBLICATION",
    "PUBLIC_YOUTUBE",
    "FORCE_PUSH",
    "SECRET_ACCESS",
})

ACTIVITY_EVENT_TYPES = frozenset({
    "WOKE",
    "OBSERVED",
    "FOUND_OPPORTUNITY",
    "STARTED_TASK",
    "SPAWNED_SUBAGENT",
    "WAITING",
    "REQUESTED_APPROVAL",
    "COMPLETED",
    "FAILED",
    "PAUSED",
    "RESUMED",
})

CUSTOM_RULE_EFFECTS = frozenset({
    "ALLOW",
    "PREAPPROVE_IF_EXPLICITLY_REQUESTED",
    "ASK",
    "HAND_OFF_TO_HUMAN",
    "BLOCK",
})

class PersistentBudgetExhausted(PermissionError):
    code = "BUDGET_EXHAUSTED"

    def __init__(self, dimension: str):
        super().__init__(f"BUDGET_EXHAUSTED:{dimension}")
        self.dimension = dimension




def _text(value: Any, name: str, *, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    result = value.strip()
    if len(result) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return result


def _identifier(value: Any, name: str) -> str:
    result = _text(value, name, maximum=192)
    if not _ID_RE.fullmatch(result):
        raise ValueError(f"{name} contains invalid characters")
    return result


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return dict(value)


def _tuple(value: Any, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if value is None and allow_empty:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list")
    result = tuple(_text(item, name, maximum=500) for item in value)
    if not allow_empty and not result:
        raise ValueError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return result


def _iso(value: Any, name: str) -> str:
    result = _text(value, name, maximum=64)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include timezone")
    return result


def _int(value: Any, name: str, *, minimum: int = 0, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return float(value)


def _digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class ProactiveResearchPolicy:
    policy_id: str
    mode: str
    allowed_actions: tuple[str, ...]
    allowed_sources: tuple[str, ...]
    max_items_per_wake: int
    schema: str = "ProactiveResearchPolicy/v1"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProactiveResearchPolicy":
        if not isinstance(value, Mapping):
            raise ValueError("ProactiveResearchPolicy must be an object")
        mode = _text(value.get("mode"), "mode", maximum=32).upper()
        if mode != "READ_ONLY":
            raise ValueError("proactive research must be read-only")
        actions = tuple(item.upper() for item in _tuple(
            value.get("allowed_actions"), "allowed_actions", allow_empty=False
        ))
        forbidden = [
            action for action in actions
            if action in PROACTIVE_FORBIDDEN_SIDE_EFFECTS
            or action not in PROACTIVE_READ_ONLY_ACTIONS
        ]
        if forbidden:
            raise ValueError(
                "proactive research read-only policy forbids actions: "
                + ",".join(sorted(forbidden))
            )
        return cls(
            policy_id=_identifier(value.get("policy_id"), "policy_id"),
            mode=mode,
            allowed_actions=actions,
            allowed_sources=_tuple(
                value.get("allowed_sources"), "allowed_sources", allow_empty=False
            ),
            max_items_per_wake=_int(
                value.get("max_items_per_wake"),
                "max_items_per_wake",
                minimum=1,
                maximum=10_000,
            ),
        )

    def allows(self, action: str) -> bool:
        candidate = str(action or "").strip().upper()
        return candidate in self.allowed_actions and candidate not in PROACTIVE_FORBIDDEN_SIDE_EFFECTS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentWorkTimeBudget:
    maximum_wall_clock_per_wake_seconds: int
    maximum_total_active_time_per_day_seconds: int
    maximum_agent_turns: int
    maximum_semantic_calls: int
    maximum_provider_calls: int
    maximum_tool_calls: int
    maximum_subagents: int
    maximum_subagent_time_seconds: int
    maximum_retries: int
    maximum_external_tool_time_seconds: int
    maximum_cost_per_wake: float
    maximum_cost_per_day: float
    schema: str = "PersistentWorkTimeBudget/v1"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PersistentWorkTimeBudget":
        if not isinstance(value, Mapping):
            raise ValueError("PersistentWorkTimeBudget must be an object")
        wall = _int(
            value.get("maximum_wall_clock_per_wake_seconds"),
            "maximum_wall_clock_per_wake_seconds",
            minimum=1,
            maximum=86_400,
        )
        daily = _int(
            value.get("maximum_total_active_time_per_day_seconds"),
            "maximum_total_active_time_per_day_seconds",
            minimum=1,
            maximum=86_400,
        )
        if wall > daily:
            raise ValueError("per-wake wall clock cannot exceed daily active time")
        cost_wake = _number(
            value.get("maximum_cost_per_wake"),
            "maximum_cost_per_wake",
        )
        cost_day = _number(
            value.get("maximum_cost_per_day"),
            "maximum_cost_per_day",
        )
        if cost_wake > cost_day:
            raise ValueError("per-wake cost cannot exceed daily cost")
        return cls(
            maximum_wall_clock_per_wake_seconds=wall,
            maximum_total_active_time_per_day_seconds=daily,
            maximum_agent_turns=_int(
                value.get("maximum_agent_turns"),
                "maximum_agent_turns",
                minimum=1,
                maximum=100_000,
            ),
            maximum_semantic_calls=_int(
                value.get("maximum_semantic_calls"),
                "maximum_semantic_calls",
                minimum=0,
                maximum=100_000,
            ),
            maximum_provider_calls=_int(
                value.get("maximum_provider_calls"),
                "maximum_provider_calls",
                minimum=0,
                maximum=100_000,
            ),
            maximum_tool_calls=_int(
                value.get("maximum_tool_calls"),
                "maximum_tool_calls",
                minimum=0,
                maximum=100_000,
            ),
            maximum_subagents=_int(
                value.get("maximum_subagents"),
                "maximum_subagents",
                minimum=0,
                maximum=1_000,
            ),
            maximum_subagent_time_seconds=_int(
                value.get("maximum_subagent_time_seconds"),
                "maximum_subagent_time_seconds",
                minimum=0,
                maximum=86_400,
            ),
            maximum_retries=_int(
                value.get("maximum_retries"),
                "maximum_retries",
                minimum=0,
                maximum=1_000,
            ),
            maximum_external_tool_time_seconds=_int(
                value.get("maximum_external_tool_time_seconds"),
                "maximum_external_tool_time_seconds",
                minimum=0,
                maximum=86_400,
            ),
            maximum_cost_per_wake=cost_wake,
            maximum_cost_per_day=cost_day,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentResponsibility:
    responsibility_id: str
    owner: str
    name: str
    description: str
    business_outcome: str
    domain: str
    task_classes: tuple[str, ...]
    priority: int
    enabled: bool
    created_at: str
    updated_at: str
    trigger_policy: dict[str, Any]
    proactive_research_policy: ProactiveResearchPolicy
    allowed_sources: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_skills: tuple[str, ...]
    allowed_agents: tuple[str, ...]
    allowed_side_effects: tuple[str, ...]
    approval_policy: dict[str, Any]
    risk_class: str
    time_budget: PersistentWorkTimeBudget
    compute_budget: dict[str, Any]
    cost_budget: dict[str, Any]
    observation_interval: dict[str, Any]
    event_triggers: tuple[str, ...]
    wake_conditions: tuple[str, ...]
    context_policy: dict[str, Any]
    memory_policy: dict[str, Any]
    artifact_policy: dict[str, Any]
    success_metrics: tuple[str, ...]
    failure_conditions: tuple[str, ...]
    escalation_policy: dict[str, Any]
    pause_policy: dict[str, Any]
    current_revision: int
    status: str
    schema: str = "PersistentResponsibility/v1"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PersistentResponsibility":
        if not isinstance(value, Mapping):
            raise ValueError("PersistentResponsibility must be an object")
        proactive_raw = value.get("proactive_research_policy")
        proactive = (
            proactive_raw
            if isinstance(proactive_raw, ProactiveResearchPolicy)
            else ProactiveResearchPolicy.from_mapping(_mapping(proactive_raw, "proactive_research_policy"))
        )
        budget_raw = value.get("time_budget")
        budget = (
            budget_raw
            if isinstance(budget_raw, PersistentWorkTimeBudget)
            else PersistentWorkTimeBudget.from_mapping(_mapping(budget_raw, "time_budget"))
        )
        allowed_sources = _tuple(value.get("allowed_sources"), "allowed_sources", allow_empty=False)
        if not set(proactive.allowed_sources).issubset(set(allowed_sources)):
            raise ValueError("proactive research sources escape responsibility allowed_sources")
        risk_class = _identifier(value.get("risk_class"), "risk_class").upper()
        side_effects = _tuple(value.get("allowed_side_effects"), "allowed_side_effects")
        if "READ_ONLY_BACKGROUND" in risk_class and side_effects:
            raise ValueError("read-only background responsibility cannot allow side effects")
        status = _text(value.get("status"), "status", maximum=32).upper()
        if status not in {
            "DORMANT",
            "WOKEN",
            "OBSERVING",
            "TASK_CREATED",
            "EXECUTING",
            "VERIFYING",
            "LEARNING",
            "WAITING",
            "PAUSED",
            "FAILED",
            "BLOCKED",
            "DISABLED",
        }:
            raise ValueError("invalid persistent responsibility status")
        enabled = value.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        return cls(
            responsibility_id=_identifier(value.get("responsibility_id"), "responsibility_id"),
            owner=_identifier(value.get("owner"), "owner"),
            name=_text(value.get("name"), "name", maximum=200),
            description=_text(value.get("description"), "description", maximum=4000),
            business_outcome=_text(value.get("business_outcome"), "business_outcome", maximum=4000),
            domain=_identifier(value.get("domain"), "domain"),
            task_classes=_tuple(value.get("task_classes"), "task_classes", allow_empty=False),
            priority=_int(value.get("priority"), "priority", minimum=0, maximum=100),
            enabled=enabled,
            created_at=_iso(value.get("created_at"), "created_at"),
            updated_at=_iso(value.get("updated_at"), "updated_at"),
            trigger_policy=_mapping(value.get("trigger_policy"), "trigger_policy"),
            proactive_research_policy=proactive,
            allowed_sources=allowed_sources,
            allowed_tools=_tuple(value.get("allowed_tools"), "allowed_tools"),
            allowed_skills=_tuple(value.get("allowed_skills"), "allowed_skills"),
            allowed_agents=_tuple(value.get("allowed_agents"), "allowed_agents"),
            allowed_side_effects=side_effects,
            approval_policy=_mapping(value.get("approval_policy"), "approval_policy"),
            risk_class=risk_class,
            time_budget=budget,
            compute_budget=_mapping(value.get("compute_budget"), "compute_budget"),
            cost_budget=_mapping(value.get("cost_budget"), "cost_budget"),
            observation_interval=_mapping(value.get("observation_interval"), "observation_interval"),
            event_triggers=_tuple(value.get("event_triggers"), "event_triggers"),
            wake_conditions=_tuple(value.get("wake_conditions"), "wake_conditions", allow_empty=False),
            context_policy=_mapping(value.get("context_policy"), "context_policy"),
            memory_policy=_mapping(value.get("memory_policy"), "memory_policy"),
            artifact_policy=_mapping(value.get("artifact_policy"), "artifact_policy"),
            success_metrics=_tuple(value.get("success_metrics"), "success_metrics", allow_empty=False),
            failure_conditions=_tuple(value.get("failure_conditions"), "failure_conditions"),
            escalation_policy=_mapping(value.get("escalation_policy"), "escalation_policy"),
            pause_policy=_mapping(value.get("pause_policy"), "pause_policy"),
            current_revision=_int(value.get("current_revision"), "current_revision", minimum=1),
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentAgentIdentity:
    persistent_agent_id: str
    responsibility_id: str
    role: str
    runtime_family: str
    agent_instance_id: str
    provider: str
    model: str
    environment_id: str
    session_id: str
    revision: int
    capability_profile_ref: str
    authorization_profile_ref: str
    schema: str = "PersistentAgentIdentity/v1"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PersistentAgentIdentity":
        if not isinstance(value, Mapping):
            raise ValueError("PersistentAgentIdentity must be an object")
        return cls(
            persistent_agent_id=_identifier(value.get("persistent_agent_id"), "persistent_agent_id"),
            responsibility_id=_identifier(value.get("responsibility_id"), "responsibility_id"),
            role=_identifier(value.get("role"), "role"),
            runtime_family=_identifier(value.get("runtime_family"), "runtime_family"),
            agent_instance_id=_identifier(value.get("agent_instance_id"), "agent_instance_id"),
            provider=_identifier(value.get("provider"), "provider"),
            model=_identifier(value.get("model"), "model"),
            environment_id=_identifier(value.get("environment_id"), "environment_id"),
            session_id=_identifier(value.get("session_id"), "session_id"),
            revision=_int(value.get("revision"), "revision", minimum=1),
            capability_profile_ref=_identifier(
                value.get("capability_profile_ref"), "capability_profile_ref"
            ),
            authorization_profile_ref=_identifier(
                value.get("authorization_profile_ref"), "authorization_profile_ref"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentCustomRule:
    rule_id: str
    responsibility_id: str
    effect: str
    action: str
    target: str
    risk_class: str
    conditions: dict[str, Any]
    revision: int
    status: str
    schema: str = "AgentCustomRule/v1"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgentCustomRule":
        if not isinstance(value, Mapping):
            raise ValueError("AgentCustomRule must be an object")
        effect = _text(value.get("effect"), "effect", maximum=64).upper()
        if effect not in CUSTOM_RULE_EFFECTS:
            raise ValueError("invalid AgentCustomRule effect")
        status = _text(value.get("status"), "status", maximum=32).upper()
        if status not in {"ACTIVE", "DISABLED", "SUPERSEDED"}:
            raise ValueError("invalid AgentCustomRule status")
        target = _text(value.get("target"), "target", maximum=1000)
        return cls(
            rule_id=_identifier(value.get("rule_id"), "rule_id"),
            responsibility_id=_identifier(value.get("responsibility_id"), "responsibility_id"),
            effect=effect,
            action=_identifier(value.get("action"), "action").upper(),
            target=target,
            risk_class=_identifier(value.get("risk_class"), "risk_class").upper(),
            conditions=_mapping(value.get("conditions"), "conditions"),
            revision=_int(value.get("revision"), "revision", minimum=1),
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistentAgentActivity:
    activity_id: str
    responsibility_id: str
    persistent_agent_id: str
    event_type: str
    occurred_at: str
    task_id: str | None
    mission_id: str | None
    summary: str
    evidence_refs: tuple[str, ...]
    payload_digest: str
    schema: str = "PersistentAgentActivity/v1"

    @classmethod
    def create(
        cls,
        *,
        responsibility_id: str,
        persistent_agent_id: str,
        event_type: str,
        occurred_at: str,
        task_id: str | None,
        mission_id: str | None,
        summary: str,
        evidence_refs: tuple[str, ...],
    ) -> "PersistentAgentActivity":
        event = _text(event_type, "event_type", maximum=64).upper()
        if event not in ACTIVITY_EVENT_TYPES:
            raise ValueError("invalid event_type")
        payload = {
            "responsibility_id": _identifier(responsibility_id, "responsibility_id"),
            "persistent_agent_id": _identifier(persistent_agent_id, "persistent_agent_id"),
            "event_type": event,
            "occurred_at": _iso(occurred_at, "occurred_at"),
            "task_id": None if task_id in (None, "") else _identifier(task_id, "task_id"),
            "mission_id": None if mission_id in (None, "") else _identifier(mission_id, "mission_id"),
            "summary": _text(summary, "summary", maximum=2000),
            "evidence_refs": tuple(str(item) for item in evidence_refs if str(item)),
        }
        digest = _digest(payload)
        return cls(
            activity_id=f"activity:{digest[:32]}",
            payload_digest=digest,
            **payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResponsibilityWakeDecision:
    responsibility_id: str
    should_wake: bool
    reason: str
    next_status: str
    dispatch_count: int
    time_budget_seconds: int
    observed_at: str
    schema: str = "ResponsibilityWakeDecision/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EffectivePermissionDecision:
    requested_permission: str
    allowed: bool
    reason: str
    rule_effect: str
    task_allows: bool
    lease_allows: bool
    responsibility_allows: bool
    harness_policy_allows: bool
    schema: str = "EffectivePermissionDecision/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionRuleDecision:
    effect: str
    matched_rule_ids: tuple[str, ...]
    grants_authority: bool = False
    schema: str = "ActionRuleDecision/v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ACTIVITY_EVENT_TYPES",
    "CUSTOM_RULE_EFFECTS",
    "PROACTIVE_FORBIDDEN_SIDE_EFFECTS",
    "PROACTIVE_READ_ONLY_ACTIONS",
    "ActionRuleDecision",
    "AgentCustomRule",
    "EffectivePermissionDecision",
    "PersistentAgentActivity",
    "PersistentAgentIdentity",
    "PersistentBudgetExhausted",
    "PersistentResponsibility",
    "PersistentWorkTimeBudget",
    "ProactiveResearchPolicy",
    "ResponsibilityWakeDecision",
]
