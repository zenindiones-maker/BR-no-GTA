from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable

from app.database import harness_learning_repository as learning_repository
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.continuous_operation_policy_service import load_continuous_operation_policy
from app.services.provider_health_service import semantic_provider_health

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


def _text(value: Any, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


@dataclass(frozen=True)
class CollaborationTask:
    task_id: str
    capability_id: str
    action: str
    objective: str
    dependencies: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    expected_output: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "CollaborationTask":
        return cls(
            task_id=_text(value.get("task_id"), "task_id"),
            capability_id=_text(value.get("capability_id"), "capability_id"),
            action=_text(value.get("action"), "action").upper(),
            objective=_text(value.get("objective"), "objective"),
            dependencies=tuple(str(item).strip() for item in value.get("dependencies") or () if str(item).strip()),
            input_refs=tuple(str(item).strip() for item in value.get("input_refs") or () if str(item).strip()),
            expected_output=str(value.get("expected_output") or "").strip(),
        )


@dataclass(frozen=True)
class RoutedCollaborationTask:
    task_id: str
    capability_id: str
    action: str
    objective: str
    dependencies: tuple[str, ...]
    input_refs: tuple[str, ...]
    expected_output: str
    routing_id: str
    candidate_capability_ids: tuple[str, ...]
    selected_executor_binding: str
    selected_agent_id: str | None
    selected_skill_id: str | None
    evidence_expectations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CollaborationPlan:
    mission_id: str
    goal_id: str
    authority: str
    tasks: tuple[RoutedCollaborationTask, ...]
    execution_levels: tuple[tuple[str, ...], ...]

    @property
    def serial_steps(self) -> tuple[str, ...]:
        return tuple(level[0] for level in self.execution_levels if len(level) == 1)

    @property
    def parallel_steps(self) -> tuple[tuple[str, ...], ...]:
        return tuple(level for level in self.execution_levels if len(level) > 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "goal_id": self.goal_id,
            "authority": self.authority,
            "tasks": [task.to_dict() for task in self.tasks],
            "execution_levels": [list(level) for level in self.execution_levels],
            "serial_steps": list(self.serial_steps),
            "parallel_steps": [list(level) for level in self.parallel_steps],
        }


def _levels(tasks: Iterable[CollaborationTask]) -> tuple[tuple[str, ...], ...]:
    tasks = tuple(tasks)
    by_id = {task.task_id: task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("task_id values must be unique")
    known = set(by_id)
    for task in tasks:
        missing = set(task.dependencies) - known
        if missing:
            raise ValueError(f"unknown dependencies for {task.task_id}: {sorted(missing)}")
        if task.task_id in task.dependencies:
            raise ValueError("task cannot depend on itself")
    remaining = set(known)
    resolved: set[str] = set()
    levels: list[tuple[str, ...]] = []
    while remaining:
        ready = tuple(sorted(
            task_id for task_id in remaining
            if set(by_id[task_id].dependencies) <= resolved
        ))
        if not ready:
            raise ValueError("collaboration graph contains a dependency cycle")
        levels.append(ready)
        resolved.update(ready)
        remaining.difference_update(ready)
    return tuple(levels)


def build_collaboration_plan(
    *,
    mission_id: str,
    goal_id: str,
    tasks: Iterable[dict[str, Any] | CollaborationTask],
) -> CollaborationPlan:
    mission_id = _text(mission_id, "mission_id")
    goal_id = _text(goal_id, "goal_id")
    normalized = tuple(
        item if isinstance(item, CollaborationTask) else CollaborationTask.from_mapping(item)
        for item in tasks
    )
    execution_levels = _levels(normalized)
    routed: list[RoutedCollaborationTask] = []
    for task in normalized:
        record = GLOBAL_CAPABILITY_REGISTRY.get(task.capability_id)
        if record is None:
            raise ValueError(f"unknown capability: {task.capability_id}")
        decision = route_harness_request(
            HarnessRoutingRequest(
                intent=f"{task.objective} {task.capability_id}",
                authorized_action=task.action,
                domain=record.domain,
                goal_id=goal_id,
                required_capability_id=task.capability_id,
                fallback_allowed=False,
                provider_required=False,
                task_class=f"mission:{task.task_id}",
                learning_required=True,
            )
        )
        selected = dict(decision.policy_metadata.get("selected_implementation") or {})
        routed.append(
            RoutedCollaborationTask(
                task_id=task.task_id,
                capability_id=task.capability_id,
                action=task.action,
                objective=task.objective,
                dependencies=task.dependencies,
                input_refs=task.input_refs,
                expected_output=task.expected_output,
                routing_id=decision.routing_id,
                candidate_capability_ids=decision.candidate_capability_ids,
                selected_executor_binding=decision.selected_executor_binding,
                selected_agent_id=selected.get("agent_id"),
                selected_skill_id=selected.get("skill_id"),
                evidence_expectations=decision.evidence_expectations,
            )
        )
    return CollaborationPlan(
        mission_id=mission_id,
        goal_id=goal_id,
        authority="DEEPSEEK_HARNESS",
        tasks=tuple(routed),
        execution_levels=execution_levels,
    )



@dataclass(frozen=True)
class GoalEnvelope:
    human_goal: str
    project: str
    goal_id: str
    subject: str | None
    mission_class: str
    source_surface: str = "telegram"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarnessMissionPlan:
    mission_id: str
    plan_id: str
    goal: GoalEnvelope
    collaboration_plan: CollaborationPlan
    bounded_memory_context: dict[str, Any]
    resource_bounds: dict[str, int]
    provider_health: dict[str, Any]
    selected_by_competence: bool
    known_bad_paths_avoided: tuple[str, ...]
    human_gates: tuple[str, ...]
    authority: str = "DEEPSEEK_HARNESS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "goal": self.goal.to_dict(),
            "collaboration_plan": self.collaboration_plan.to_dict(),
            "bounded_memory_context": dict(self.bounded_memory_context),
            "resource_bounds": dict(self.resource_bounds),
            "provider_health": dict(self.provider_health),
            "selected_by_competence": self.selected_by_competence,
            "known_bad_paths_avoided": list(self.known_bad_paths_avoided),
            "human_gates": list(self.human_gates),
            "authority": self.authority,
        }


def _goal_class(text: str) -> str:
    folded = re.sub(r"\s+", " ", str(text or "").strip().casefold())
    if (
        any(term in folded for term in (
            "sistema", "pipeline", "desempenho", "performance", "latencia",
            "latência", "demorando", "lento", "telegram",
        ))
        and any(term in folded for term in (
            "melhora", "melhore", "melhorar", "corrige", "corrija", "corrigir",
            "otimiza", "otimize", "otimizar", "analisa", "analise", "analisar",
            "descobre", "descobrir", "investiga", "investigue", "investigar",
            "resolve", "resolver",
        ))
    ):
        return "SYSTEM_IMPROVEMENT"
    if any(term in folded for term in (
        "gta 6", "gta6", "rockstar", "vice city", "jason", "lucia", "leonida",
    )):
        return "GTA6_INTELLIGENCE"
    if any(term in folded for term in (
        "roteiro", "editorial", "pauta", "thumbnail", "seo", "ctr", "repetitivo",
    )):
        return "EDITORIAL"
    return "OPEN_SEMANTIC"


def build_goal_envelope(
    *,
    human_goal: str,
    project: str,
    goal_id: str,
    subject: str | None = None,
    source_surface: str = "telegram",
) -> GoalEnvelope:
    goal = _text(human_goal, "human_goal")
    normalized_subject = str(subject).strip() if subject else None
    classification_text = " ".join(
        item for item in (goal, normalized_subject) if item
    )
    return GoalEnvelope(
        human_goal=goal,
        project=_text(project or "BR-no-GTA", "project"),
        goal_id=_text(goal_id or "human-goal", "goal_id"),
        subject=normalized_subject,
        mission_class=_goal_class(classification_text),
        source_surface=str(source_surface or "telegram"),
    )


def _mission_requirements(goal: GoalEnvelope) -> list[dict[str, Any]]:
    folded = goal.human_goal.casefold()
    if goal.mission_class == "SYSTEM_IMPROVEMENT":
        tasks = [
            {
                "task_id": "measure",
                "task_class": "system-performance-measure",
                "action": "DEVELOPMENT",
                "query": "system improvement performance observability evidence measure",
                "dependencies": [],
                "expected_output": "MeasuredProblemEvidence",
            },
            {
                "task_id": "root-cause",
                "task_class": "system-root-cause-analysis",
                "action": "DEVELOPMENT",
                "query": "agent-office codex readonly analysis debugging architecture reliability",
                "dependencies": ["measure"],
                "expected_output": "RootCauseEvidence",
            },
        ]
        if any(term in folded for term in ("corrig", "melhor", "otimiz")):
            tasks.extend([
                {
                    "task_id": "candidate",
                    "task_class": "bounded-development",
                    "action": "DEVELOPMENT",
                    "query": "agent-office codex bounded development candidate worktree",
                    "dependencies": ["root-cause"],
                    "expected_output": "BoundedCandidatePatch",
                },
                {
                    "task_id": "validate",
                    "task_class": "candidate-validation",
                    "action": "DEVELOPMENT",
                    "query": "agent-office codex readonly analysis review quality test benchmark",
                    "dependencies": ["candidate"],
                    "expected_output": "BaselineCandidateComparison",
                },
            ])
        return tasks
    if goal.mission_class == "GTA6_INTELLIGENCE":
        tasks = [
            {
                "task_id": "research",
                "task_class": "gta6-research",
                "action": "RESEARCH",
                "query": "gta6 research official source",
                "dependencies": [],
                "expected_output": "ResearchEvidence",
            },
            {
                "task_id": "fact-check",
                "task_class": "gta6-fact-check",
                "action": "RESEARCH",
                "query": "gta6 fact-check claims evidence",
                "dependencies": ["research"],
                "expected_output": "VerifiedClaims",
            },
        ]
        if any(term in folded for term in ("video", "vídeo", "pauta", "roteiro", "rende")):
            tasks.append({
                "task_id": "editorial",
                "task_class": "youtube-content-strategy",
                "action": "EDITORIAL",
                "query": "youtube content strategy editorial opportunity",
                "dependencies": ["fact-check"],
                "expected_output": "EditorialOpportunity",
            })
        return tasks
    if goal.mission_class == "EDITORIAL":
        return [
            {
                "task_id": "strategy",
                "task_class": "youtube-content-strategy",
                "action": "EDITORIAL",
                "query": "youtube content strategy editorial",
                "dependencies": [],
                "expected_output": "EditorialStrategy",
            },
            {
                "task_id": "review",
                "task_class": "youtube-script-review",
                "action": "EDITORIAL",
                "query": "youtube script review quality",
                "dependencies": ["strategy"],
                "expected_output": "ScriptReview",
            },
        ]
    return []


def _blocked_by_known_failure(record, health: dict[str, Any]) -> bool:
    opencode = dict(health.get("opencode") or {})
    blocked = opencode.get("state") in {"UPSTREAM_DENIED", "BLOCKED", "QUARANTINED"}
    if not blocked:
        return False
    return bool(
        record.provider_id == "opencode"
        or "semantic-skill" in record.policy_tags
        or any("ai.reasoning.text" in str(item).casefold() for item in record.requirements)
    )


def _select_requirement(
    requirement: dict[str, Any],
    *,
    health: dict[str, Any],
    used: set[str],
) -> tuple[str, bool, bool]:
    discovered = GLOBAL_CAPABILITY_REGISTRY.discover(
        intent=str(requirement["query"]),
        authorized_action=str(requirement["action"]),
        limit=30,
    )
    ranked: list[tuple[float, str, bool]] = []
    bad_path_avoided = False
    for item in discovered:
        capability_id = str(item["capability_id"])
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        if record is None or not record.execution_enabled:
            continue
        if _blocked_by_known_failure(record, health):
            bad_path_avoided = True
            continue
        competence = learning_repository.list_competence(
            task_class=str(requirement["task_class"]),
            capability_id=capability_id,
            status="ACTIVE",
            limit=10,
        )
        if not competence:
            competence = learning_repository.list_competence(
                capability_id=capability_id,
                status="ACTIVE",
                limit=10,
            )
        competence_score = 0.0
        competence_used = False
        for row in competence:
            tested = max(1, int(row.get("tested_cases") or 0))
            score = (
                8.0 * float(row.get("success_count") or 0) / tested
                - 6.0 * float(row.get("failure_count") or 0) / tested
                - 2.0 * float(row.get("human_correction_count") or 0) / tested
            )
            competence_score = max(competence_score, score)
            competence_used = True
        duplicate_penalty = 1.5 if capability_id in used else 0.0
        lexical_rank = max(0.0, 8.0 - float(len(ranked)) * 0.2)
        ranked.append((
            lexical_rank + competence_score - duplicate_penalty,
            capability_id,
            competence_used,
        ))
    if not ranked:
        raise RuntimeError(
            f"no healthy Registry capability for task_class={requirement['task_class']}"
        )
    ranked.sort(key=lambda row: (-row[0], row[1]))
    _, capability_id, competence_used = ranked[0]
    return capability_id, competence_used, bad_path_avoided


def plan_mission_from_human_goal(
    goal: GoalEnvelope,
    *,
    artifact_ref: str | None = None,
) -> HarnessMissionPlan:
    policy = load_continuous_operation_policy()
    resources = dict(policy.resource_governance)
    health = semantic_provider_health()
    requirements = _mission_requirements(goal)
    if not requirements:
        if not health.get("semantic_reasoning_available"):
            raise RuntimeError("SEMANTIC_REASONING_PROVIDER_UNAVAILABLE")
        raise RuntimeError("MISSION_REQUIREMENTS_UNRESOLVED")

    requirements = requirements[: int(resources["max_tasks_per_mission"])]
    domain = {
        "SYSTEM_IMPROVEMENT": "system-improvement",
        "GTA6_INTELLIGENCE": "research",
        "EDITORIAL": "youtube",
    }[goal.mission_class]
    memory = build_bounded_memory_context(
        goal_id=goal.goal_id,
        domain=domain,
        task_class=goal.mission_class.casefold().replace("_", "-"),
        artifact_ref=artifact_ref,
        intent=goal.human_goal,
        max_bytes=int(resources["bounded_memory_bytes"]),
    ).to_dict()

    selected_tasks = []
    used: set[str] = set()
    competence_used = False
    bad_path_avoided = False
    for requirement in requirements:
        capability_id, used_competence, avoided = _select_requirement(
            requirement,
            health=health,
            used=used,
        )
        competence_used = competence_used or used_competence
        bad_path_avoided = bad_path_avoided or avoided
        used.add(capability_id)
        selected_tasks.append({
            "task_id": requirement["task_id"],
            "capability_id": capability_id,
            "action": requirement["action"],
            "objective": f"{goal.human_goal} :: {requirement['task_class']}",
            "dependencies": requirement["dependencies"],
            "input_refs": [artifact_ref] if artifact_ref else [],
            "expected_output": requirement["expected_output"],
        })

    fingerprint = sha256(json.dumps(
        {"goal": goal.to_dict(), "tasks": selected_tasks},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()[:20]
    mission_id = f"mission-{fingerprint}"
    plan_id = f"plan-{fingerprint}"
    collaboration = build_collaboration_plan(
        mission_id=mission_id,
        goal_id=goal.goal_id,
        tasks=selected_tasks,
    )
    return HarnessMissionPlan(
        mission_id=mission_id,
        plan_id=plan_id,
        goal=goal,
        collaboration_plan=collaboration,
        bounded_memory_context=memory,
        resource_bounds={
            key: int(resources[key])
            for key in (
                "max_tasks_per_mission",
                "max_retries_per_task",
                "max_reviewer_loops",
                "max_parallelism",
                "mission_timeout_seconds",
                "bounded_memory_bytes",
            )
        },
        provider_health=health,
        selected_by_competence=competence_used,
        known_bad_paths_avoided=(
            ("opencode_free_tier_403",) if bad_path_avoided else ()
        ),
        human_gates=(
            ("promotion",)
            if any(task["task_id"] == "candidate" for task in selected_tasks)
            else ()
        ),
    )
