from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from app.services.harness_agent_fleet_projection_service import AgentCapabilityProfile


@dataclass(frozen=True)
class TaskTopologyInput:
    required_roles: tuple[str, ...]
    dependency_density: float
    parallelizable_branch_count: int
    shared_mutable_state: bool
    tool_count: int
    write_set_overlap: bool
    context_coupling: float
    risk_class: str
    need_for_independence: bool
    estimated_coordination_overhead: float
    mutation_required: bool
    durable_coordination_required: bool
    reduction_required: bool


@dataclass(frozen=True)
class TaskTopologyAssessment:
    topology: str
    reasons: tuple[str, ...]
    evidence: dict[str, Any]
    schema: str = "TaskTopologyAssessment/v1"


@dataclass(frozen=True)
class AgentEffortBudget:
    complexity: str
    max_agents: int
    max_subagents: int
    max_depth: int
    max_tool_calls: int
    max_provider_calls: int
    max_context_bytes: int
    max_tokens: int
    max_wall_clock_seconds: int
    max_candidate_revisions: int
    schema: str = "AgentEffortBudget/v1"

    @classmethod
    def for_complexity(cls, complexity: str) -> "AgentEffortBudget":
        key = str(complexity or "").strip().upper()
        presets = {
            "TRIVIAL": (1, 0, 1, 8, 1, 32768, 12000, 300, 1),
            "STANDARD": (2, 2, 1, 24, 4, 65536, 40000, 900, 2),
            "COMPLEX": (4, 4, 2, 64, 10, 131072, 120000, 1800, 3),
            "DEEP_RESEARCH": (5, 6, 2, 96, 16, 196608, 200000, 3600, 3),
            "CRITICAL_INCIDENT": (6, 6, 2, 120, 20, 262144, 240000, 3600, 4),
        }
        if key not in presets:
            raise ValueError("unsupported complexity")
        vals = presets[key]
        return cls(key, *vals)


def assess_task_topology(value: TaskTopologyInput) -> TaskTopologyAssessment:
    roles = {str(role).upper() for role in value.required_roles}
    reasons: list[str] = []
    if value.durable_coordination_required:
        topology = "HIERARCHICAL"
        reasons.append("DURABLE_COORDINATION_REQUIRED")
    elif (
        value.mutation_required
        and value.reduction_required
        and value.parallelizable_branch_count > 1
    ):
        topology = "HYBRID"
        reasons += ["PARALLEL_ANALYSIS", "SERIAL_MUTATION"]
    elif (
        value.mutation_required
        and value.need_for_independence
        and "INDEPENDENT_REVIEW" in roles
    ):
        topology = "MAKER_CHECKER"
        reasons.append("MUTATION_REQUIRES_INDEPENDENT_REVIEW")
    elif value.parallelizable_branch_count > 1 and value.reduction_required:
        topology = "PARALLEL_WITH_REDUCTION"
        reasons.append("INDEPENDENT_EVIDENCE_REQUIRES_HARNESS_FAN_IN")
    elif (
        value.parallelizable_branch_count > 1
        and not value.shared_mutable_state
        and not value.write_set_overlap
        and value.dependency_density < 0.5
        and value.context_coupling < 0.6
    ):
        topology = "PARALLEL_INDEPENDENT"
        reasons.append("INDEPENDENT_BRANCHES")
    elif (
        value.dependency_density >= 0.5
        or value.shared_mutable_state
        or value.write_set_overlap
    ):
        topology = "SEQUENTIAL"
        reasons.append("DEPENDENCY_OR_SHARED_MUTABLE_STATE")
    else:
        topology = "SINGLE_AGENT"
        reasons.append("LOW_COORDINATION_SINGLE_CAPABILITY_PATH")

    return TaskTopologyAssessment(
        topology=topology,
        reasons=tuple(reasons),
        evidence={
            "dependency_density": float(value.dependency_density),
            "parallelizable_branch_count": int(value.parallelizable_branch_count),
            "shared_mutable_state": bool(value.shared_mutable_state),
            "tool_count": int(value.tool_count),
            "write_set_overlap": bool(value.write_set_overlap),
            "context_coupling": float(value.context_coupling),
            "risk_class": str(value.risk_class),
            "need_for_independence": bool(value.need_for_independence),
            "estimated_coordination_overhead": float(value.estimated_coordination_overhead),
            "mutation_required": bool(value.mutation_required),
            "reduction_required": bool(value.reduction_required),
        },
    )


@dataclass(frozen=True)
class ImprovementCoalitionPlan:
    mission_id: str
    task_id: str
    topology: str
    required_roles: tuple[str, ...]
    selected_capability_ids: tuple[str, ...]
    selected_agent_ids: tuple[str, ...]
    rejected_candidates: tuple[dict[str, Any], ...]
    agents_considered: int
    agents_selected: int
    same_backend_independence_limitation: bool
    selection_digest: str
    schema: str = "ImprovementCoalitionPlan/v1"


def _score(metrics: dict[str, Any]) -> float:
    positive_keys = (
        "task_class_competence",
        "domain_competence",
        "verified_success_rate",
        "review_accept_rate",
        "health_score",
        "latency_efficiency",
        "cost_efficiency",
        "tool_efficiency",
        "context_efficiency",
        "freshness",
    )
    negative_keys = (
        "failure_penalty",
        "critical_regression_penalty",
        "human_correction_penalty",
    )
    return sum(float(metrics.get(k, 0)) for k in positive_keys) - sum(
        float(metrics.get(k, 0)) for k in negative_keys
    )


def _candidate_key(
    item: tuple[AgentCapabilityProfile, dict[str, Any]],
) -> tuple[float, str]:
    profile, metrics = item
    return (-_score(metrics), profile.capability_id)


def _search_min_cover(
    eligible: tuple[tuple[AgentCapabilityProfile, dict[str, Any]], ...],
    required_roles: tuple[str, ...],
    max_agents: int,
) -> list[tuple[AgentCapabilityProfile, dict[str, Any]]]:
    required = set(required_roles)
    by_role: dict[str, list[tuple[AgentCapabilityProfile, dict[str, Any]]]] = {
        role: [
            item for item in eligible
            if role in set(item[0].functional_roles)
        ]
        for role in required
    }
    missing = [role for role, rows in by_role.items() if not rows]
    if missing:
        raise RuntimeError("NO_ELIGIBLE_CAPABILITY_FOR_ROLE:" + ",".join(sorted(missing)))

    best: list[tuple[AgentCapabilityProfile, dict[str, Any]]] | None = None
    best_score: float | None = None

    def recurse(
        chosen: list[tuple[AgentCapabilityProfile, dict[str, Any]]],
        covered: set[str],
    ) -> None:
        nonlocal best, best_score
        if required <= covered:
            if len(chosen) > max_agents:
                return
            score = sum(_score(metrics) for _, metrics in chosen)
            stable = tuple(sorted(p.capability_id for p, _ in chosen))
            if (
                best is None
                or len(chosen) < len(best)
                or (
                    len(chosen) == len(best)
                    and (
                        best_score is None
                        or score > best_score
                        or (
                            score == best_score
                            and stable < tuple(sorted(p.capability_id for p, _ in best))
                        )
                    )
                )
            ):
                best = list(chosen)
                best_score = score
            return

        if len(chosen) >= max_agents:
            return
        if best is not None and len(chosen) >= len(best):
            return

        uncovered = required - covered
        role = min(
            uncovered,
            key=lambda r: (len(by_role[r]), r),
        )
        for item in sorted(by_role[role], key=_candidate_key):
            profile, _metrics = item
            if any(existing[0].capability_id == profile.capability_id for existing in chosen):
                continue
            recurse(
                chosen + [item],
                covered | (set(profile.functional_roles) & required),
            )

    recurse([], set())
    if best is None:
        raise RuntimeError("NO_VALID_COALITION")
    return best


def _validate_independence(
    selected: list[tuple[AgentCapabilityProfile, dict[str, Any]]],
    required_roles: tuple[str, ...],
) -> bool:
    if "APPLY" not in required_roles or "INDEPENDENT_REVIEW" not in required_roles:
        return False
    makers = [p for p, _ in selected if "APPLY" in p.functional_roles]
    reviewers = [p for p, _ in selected if "INDEPENDENT_REVIEW" in p.functional_roles]
    if not makers or not reviewers:
        raise RuntimeError("INDEPENDENCE_REQUIRED_BUT_ROLE_MISSING")
    for maker in makers:
        for reviewer in reviewers:
            if maker.agent_id == reviewer.agent_id:
                raise RuntimeError("INDEPENDENCE_REQUIRED_MAKER_EQUALS_REVIEWER")
    return all(
        maker.independence_group == reviewer.independence_group
        for maker in makers
        for reviewer in reviewers
    )


def build_improvement_coalition_plan(
    *,
    mission_id: str,
    task_id: str,
    required_roles: tuple[str, ...],
    topology: TaskTopologyAssessment,
    candidates: tuple[tuple[AgentCapabilityProfile, dict[str, Any]], ...],
    effort_budget: AgentEffortBudget,
) -> ImprovementCoalitionPlan:
    roles = tuple(dict.fromkeys(str(role).upper() for role in required_roles))
    harness_only = {"MISSION_AUTHORITY", "REDUCTION", "PROMOTION"}
    if harness_only.intersection(roles):
        raise ValueError("Harness-only role cannot be delegated")

    rejected: list[dict[str, Any]] = []
    eligible: list[tuple[AgentCapabilityProfile, dict[str, Any]]] = []
    for profile, metrics in candidates:
        if not profile.maturity.eligible:
            rejected.append({
                "capability_id": profile.capability_id,
                "agent_id": profile.agent_id,
                "reason": "HARD_INELIGIBLE",
                "details": list(profile.maturity.reasons),
            })
            continue
        if not set(profile.functional_roles).intersection(roles):
            rejected.append({
                "capability_id": profile.capability_id,
                "agent_id": profile.agent_id,
                "reason": "IRRELEVANT_FUNCTIONAL_ROLE",
                "details": [],
            })
            continue
        eligible.append((profile, dict(metrics or {})))

    selected = _search_min_cover(
        tuple(eligible),
        roles,
        effort_budget.max_agents,
    )
    same_backend = _validate_independence(selected, roles)

    selected_profiles = sorted(
        (profile for profile, _ in selected),
        key=lambda p: p.capability_id,
    )
    payload = {
        "schema": "ImprovementCoalitionPlan/v1",
        "mission_id": mission_id,
        "task_id": task_id,
        "topology": topology.topology,
        "required_roles": list(roles),
        "selected_capability_ids": [p.capability_id for p in selected_profiles],
        "selected_agent_ids": [p.agent_id for p in selected_profiles],
        "effort_budget": {
            "complexity": effort_budget.complexity,
            "max_agents": effort_budget.max_agents,
        },
        "same_backend_independence_limitation": same_backend,
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return ImprovementCoalitionPlan(
        mission_id=str(mission_id),
        task_id=str(task_id),
        topology=topology.topology,
        required_roles=roles,
        selected_capability_ids=tuple(p.capability_id for p in selected_profiles),
        selected_agent_ids=tuple(p.agent_id for p in selected_profiles),
        rejected_candidates=tuple(rejected),
        agents_considered=len(candidates),
        agents_selected=len(selected_profiles),
        same_backend_independence_limitation=same_backend,
        selection_digest=digest,
    )
