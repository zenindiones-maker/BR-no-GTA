from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable, Iterable

from app.database import harness_learning_repository as learning_repository
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.continuous_operation_policy_service import load_continuous_operation_policy
from app.services.provider_health_service import semantic_provider_health
from app.services.harness_adaptive_planning_service import (
    build_semantic_planning_context,
    proposal_requirements,
    propose_validated_semantic_plan,
    select_capability_for_requirement,
)

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
class TaskEnvelope:
    """Canonical Harness task contract.

    Planning is capability-first. Agent/executor identities are added only after
    Registry selection and Routing/Policy validation.
    """

    task_id: str
    capability_id: str
    action: str
    objective: str
    dependencies: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    expected_output: str = ""
    task_class: str = "GENERAL"
    required_capability_description: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    candidate_requirement: str = "REQUIRED"
    read_scope: tuple[str, ...] = ()
    write_scope: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    allowed_side_effects: tuple[str, ...] = ()
    forbidden_side_effects: tuple[str, ...] = (
        "publication",
        "policy_mutation",
        "authority_mutation",
        "canonical_memory_write",
        "secret_access",
    )
    time_budget_seconds: int = 300
    cost_budget: float = 0.0
    context_budget_bytes: int = 32768
    tool_budget: int = 16
    retry_budget: int = 1
    evidence_contract: str = ""
    review_policy: str = "INDEPENDENT_IF_MUTATING"
    risk_side_effect_class: str = "READ_ONLY"
    idempotency_key: str = ""
    expires_at: str = ""
    human_gate_policy: str = "NONE"
    mission_id: str = "UNBOUND"
    goal_id: str = "UNBOUND"

    @property
    def authorized_action(self) -> str:
        return self.action

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TaskEnvelope":
        dependencies = tuple(
            str(item).strip()
            for item in value.get("dependencies") or ()
            if str(item).strip()
        )
        input_refs = tuple(
            str(item).strip()
            for item in value.get("input_refs") or ()
            if str(item).strip()
        )
        acceptance = tuple(
            str(item).strip()
            for item in value.get("acceptance_criteria") or ()
            if str(item).strip()
        )
        expected = str(value.get("expected_output") or "").strip()
        if not acceptance and expected:
            acceptance = (f"produce {expected}",)
        write_scope = tuple(
            str(item).strip().replace("\\", "/").strip("/")
            for item in value.get("write_scope") or ()
            if str(item).strip()
        )
        read_scope = tuple(
            str(item).strip().replace("\\", "/").strip("/")
            for item in value.get("read_scope") or ()
            if str(item).strip()
        )
        for name, paths in (("read_scope", read_scope), ("write_scope", write_scope)):
            if any(".." in path.split("/") for path in paths):
                raise ValueError(f"{name} contains traversal")
        risk_class = str(
            value.get("risk_side_effect_class")
            or ("BOUNDED_MUTATION" if write_scope else "READ_ONLY")
        ).strip().upper()
        default_candidate_requirement = (
            "REQUIRED"
            if write_scope or risk_class in {"BOUNDED_MUTATION", "MUTATING", "MEDIUM", "HIGH"}
            else "NOT_APPLICABLE"
        )
        candidate_requirement = str(
            value.get("candidate_requirement") or default_candidate_requirement
        ).strip().upper()
        if candidate_requirement not in {
            "REQUIRED", "CONDITIONAL", "NOT_APPLICABLE"
        }:
            raise ValueError("candidate_requirement is invalid")
        if (
            candidate_requirement == "NOT_APPLICABLE"
            and (write_scope or risk_class in {"BOUNDED_MUTATION", "MUTATING", "MEDIUM", "HIGH"})
        ):
            raise ValueError(
                "mutating TaskEnvelope cannot mark candidate NOT_APPLICABLE"
            )
        time_budget = int(value.get("time_budget_seconds") or 300)
        context_budget = int(value.get("context_budget_bytes") or 32768)
        tool_budget = int(value.get("tool_budget") or 16)
        retry_budget = int(value.get("retry_budget") if value.get("retry_budget") is not None else 1)
        if not 1 <= time_budget <= 7200:
            raise ValueError("time_budget_seconds must be in [1, 7200]")
        if not 1024 <= context_budget <= 262144:
            raise ValueError("context_budget_bytes must be in [1024, 262144]")
        if not 0 <= tool_budget <= 1000:
            raise ValueError("tool_budget must be in [0, 1000]")
        if not 0 <= retry_budget <= 20:
            raise ValueError("retry_budget must be in [0, 20]")
        return cls(
            task_id=_text(value.get("task_id"), "task_id"),
            capability_id=_text(value.get("capability_id"), "capability_id"),
            action=_text(value.get("action") or value.get("authorized_action"), "action").upper(),
            objective=_text(value.get("objective"), "objective"),
            dependencies=dependencies,
            input_refs=input_refs,
            expected_output=expected,
            task_class=str(value.get("task_class") or value.get("task_id") or "GENERAL").strip(),
            required_capability_description=str(
                value.get("required_capability_description") or ""
            ).strip(),
            acceptance_criteria=acceptance,
            candidate_requirement=candidate_requirement,
            read_scope=read_scope,
            write_scope=write_scope,
            allowed_tools=tuple(
                str(item).strip()
                for item in value.get("allowed_tools") or ()
                if str(item).strip()
            ),
            allowed_side_effects=tuple(
                str(item).strip()
                for item in value.get("allowed_side_effects") or ()
                if str(item).strip()
            ),
            forbidden_side_effects=tuple(
                str(item).strip()
                for item in value.get("forbidden_side_effects")
                or cls.__dataclass_fields__["forbidden_side_effects"].default
                if str(item).strip()
            ),
            time_budget_seconds=time_budget,
            cost_budget=float(value.get("cost_budget") or 0.0),
            context_budget_bytes=context_budget,
            tool_budget=tool_budget,
            retry_budget=retry_budget,
            evidence_contract=str(value.get("evidence_contract") or "").strip(),
            review_policy=str(
                value.get("review_policy") or "INDEPENDENT_IF_MUTATING"
            ).strip().upper(),
            risk_side_effect_class=risk_class,
            idempotency_key=str(value.get("idempotency_key") or "").strip(),
            expires_at=str(value.get("expires_at") or "").strip(),
            human_gate_policy=str(
                value.get("human_gate_policy") or "NONE"
            ).strip().upper(),
            mission_id=str(value.get("mission_id") or "UNBOUND").strip(),
            goal_id=str(value.get("goal_id") or "UNBOUND").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["authorized_action"] = self.action
        return data


# Backward-compatible name; there is one canonical task contract.
CollaborationTask = TaskEnvelope


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
    task_class: str = "GENERAL"
    required_capability_description: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    candidate_requirement: str = "REQUIRED"
    read_scope: tuple[str, ...] = ()
    write_scope: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    allowed_side_effects: tuple[str, ...] = ()
    forbidden_side_effects: tuple[str, ...] = ()
    time_budget_seconds: int = 300
    cost_budget: float = 0.0
    context_budget_bytes: int = 32768
    tool_budget: int = 16
    retry_budget: int = 1
    evidence_contract: str = ""
    review_policy: str = "INDEPENDENT_IF_MUTATING"
    risk_side_effect_class: str = "READ_ONLY"
    idempotency_key: str = ""
    expires_at: str = ""
    human_gate_policy: str = "NONE"
    mission_id: str = "UNBOUND"
    goal_id: str = "UNBOUND"
    capability_version: str = "1"
    supports_parallelism: bool = True
    supports_retry: bool = True
    supports_resume: bool = False
    supports_review: bool = False
    selection_evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def authorized_action(self) -> str:
        return self.action

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["authorized_action"] = self.action
        return data


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


def _levels(tasks: Iterable[TaskEnvelope]) -> tuple[tuple[str, ...], ...]:
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


def _task_idempotency_key(
    *,
    mission_id: str,
    task: TaskEnvelope,
    capability_version: str,
    read_scope: tuple[str, ...],
    write_scope: tuple[str, ...],
) -> str:
    payload = {
        "mission_id": mission_id,
        "task_id": task.task_id,
        "capability_id": task.capability_id,
        "capability_version": capability_version,
        "input_refs": list(task.input_refs),
        "read_scope": list(read_scope),
        "write_scope": list(write_scope),
        "candidate_requirement": task.candidate_requirement,
        "objective": task.objective,
    }
    digest = sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"task:{digest}"


def build_collaboration_plan(
    *,
    mission_id: str,
    goal_id: str,
    tasks: Iterable[dict[str, Any] | TaskEnvelope],
) -> CollaborationPlan:
    mission_id = _text(mission_id, "mission_id")
    goal_id = _text(goal_id, "goal_id")
    normalized = tuple(
        item if isinstance(item, TaskEnvelope) else TaskEnvelope.from_mapping(item)
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
                task_class=task.task_class or f"mission:{task.task_id}",
                learning_required=True,
            )
        )
        selected = dict(decision.policy_metadata.get("selected_implementation") or {})
        read_scope = task.read_scope or tuple(record.default_read_scope)
        write_scope = task.write_scope or tuple(record.default_write_scope)
        allowed_tools = task.allowed_tools or tuple(record.allowed_tools)
        allowed_side_effects = task.allowed_side_effects or tuple(record.side_effects)
        expires_at = task.expires_at or (
            datetime.now(timezone.utc)
            + timedelta(seconds=task.time_budget_seconds)
        ).isoformat()
        idempotency_key = task.idempotency_key or _task_idempotency_key(
            mission_id=mission_id,
            task=task,
            capability_version=str(record.version or "1"),
            read_scope=read_scope,
            write_scope=write_scope,
        )
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
                task_class=task.task_class,
                required_capability_description=task.required_capability_description,
                acceptance_criteria=task.acceptance_criteria,
                candidate_requirement=task.candidate_requirement,
                read_scope=read_scope,
                write_scope=write_scope,
                allowed_tools=allowed_tools,
                allowed_side_effects=allowed_side_effects,
                forbidden_side_effects=task.forbidden_side_effects,
                time_budget_seconds=task.time_budget_seconds,
                cost_budget=task.cost_budget,
                context_budget_bytes=task.context_budget_bytes,
                tool_budget=task.tool_budget,
                retry_budget=task.retry_budget,
                evidence_contract=task.evidence_contract or str(record.evidence_contract or ""),
                review_policy=task.review_policy,
                risk_side_effect_class=(
                    task.risk_side_effect_class
                    if task.risk_side_effect_class != "READ_ONLY" or not write_scope
                    else "BOUNDED_MUTATION"
                ),
                idempotency_key=idempotency_key,
                expires_at=expires_at,
                human_gate_policy=task.human_gate_policy,
                mission_id=mission_id,
                goal_id=goal_id,
                capability_version=str(record.version or "1"),
                supports_parallelism=bool(record.supports_parallelism),
                supports_retry=bool(record.supports_retry),
                supports_resume=bool(record.supports_resume),
                supports_review=bool(record.supports_review),
                selection_evidence={
                    "routing_id": decision.routing_id,
                    "candidate_capability_ids": list(decision.candidate_capability_ids),
                    "selected_implementation": selected,
                    "policy_metadata": dict(decision.policy_metadata),
                },
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
    canonical_state: dict[str, Any] = field(default_factory=dict)
    conversation_state: dict[str, Any] = field(default_factory=dict)

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
    planning_mode: str = "DETERMINISTIC_FAST_PATH"
    semantic_plan_proposal: dict[str, Any] | None = None
    planning_evidence: dict[str, Any] = field(default_factory=dict)
    memory_influences_strategy: bool = False
    competence_influences_selection: bool = False
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
            "planning_mode": self.planning_mode,
            "semantic_plan_proposal": (
                dict(self.semantic_plan_proposal)
                if self.semantic_plan_proposal is not None
                else None
            ),
            "planning_evidence": dict(self.planning_evidence),
            "memory_influences_strategy": self.memory_influences_strategy,
            "competence_influences_selection": self.competence_influences_selection,
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
    canonical_state: dict[str, Any] | None = None,
    conversation_state: dict[str, Any] | None = None,
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
        canonical_state=dict(canonical_state or {}),
        conversation_state=dict(conversation_state or {}),
    )


def _deterministic_capability_requirements(
    goal: GoalEnvelope,
) -> list[dict[str, Any]]:
    """Capability-first fallback requirements for narrow deterministic goals.

    These are functional requirements, not agent/team assignments. Task ids are
    opaque sequence identities; executors are discovered later from Registry.
    """
    folded = goal.human_goal.casefold()
    if goal.mission_class == "SYSTEM_IMPROVEMENT":
        functions: list[dict[str, Any]] = [
            {
                "function": "OBSERVE",
                "task_class": "system-observation",
                "action": "DEVELOPMENT",
                "query": (
                    "measure observable system performance latency redundancy "
                    "work evidence without mutation"
                ),
                "required_capability_description": (
                    "read-only system observation and measurable baseline evidence"
                ),
                "expected_output": "MeasuredProblemEvidence",
                "acceptance_criteria": [
                    "baseline is measurable",
                    "evidence references are preserved",
                    "no mutation is performed",
                ],
                "risk_side_effect_class": "READ_ONLY",
            },
            {
                "function": "DIAGNOSE",
                "task_class": "root-cause-analysis",
                "action": "DEVELOPMENT",
                "query": (
                    "read-only root cause analysis source architecture performance "
                    "reliability evidence"
                ),
                "required_capability_description": (
                    "read-only root cause analysis over bounded repository scope"
                ),
                "expected_output": "RootCauseEvidence",
                "acceptance_criteria": [
                    "root cause is linked to baseline evidence",
                    "recommended scope is bounded",
                ],
                "risk_side_effect_class": "READ_ONLY",
            },
        ]
        wants_change = any(
            term in folded
            for term in (
                "corrig", "melhor", "otimiz", "implement", "reduz",
                "elimin", "remove", "refator",
            )
        )
        if wants_change:
            functions.extend([
                {
                    "function": "IMPLEMENT",
                    "task_class": "bounded-development",
                    "action": "DEVELOPMENT",
                    "query": (
                        "bounded isolated development worktree candidate code change tests"
                    ),
                    "required_capability_description": (
                        "bounded isolated code mutation producing a local candidate only"
                    ),
                    "expected_output": "BoundedCandidatePatch",
                    "acceptance_criteria": [
                        "candidate remains isolated",
                        "change stays inside authorized scope",
                        "focused regression evidence exists",
                    ],
                    "risk_side_effect_class": "BOUNDED_MUTATION",
                },
                {
                    "function": "REVIEW",
                    "task_class": "independent-review",
                    "action": "DEVELOPMENT",
                    "query": (
                        "independent read-only code review candidate diff acceptance "
                        "criteria regression evidence"
                    ),
                    "required_capability_description": (
                        "independent read-only review distinct from candidate builder"
                    ),
                    "expected_output": "IndependentReviewEvidence",
                    "acceptance_criteria": [
                        "builder and reviewer identities differ",
                        "candidate is checked against acceptance criteria",
                        "regressions are reported",
                    ],
                    "risk_side_effect_class": "READ_ONLY",
                },
                {
                    "function": "BENCHMARK",
                    "task_class": "baseline-candidate-comparison",
                    "action": "DEVELOPMENT",
                    "query": (
                        "read-only benchmark baseline candidate performance latency "
                        "quality regression comparison"
                    ),
                    "required_capability_description": (
                        "deterministic or read-only baseline versus candidate comparison"
                    ),
                    "expected_output": "BaselineCandidateComparison",
                    "acceptance_criteria": [
                        "baseline and candidate use comparable metrics",
                        "improvement delta is explicit",
                        "quality does not regress",
                    ],
                    "risk_side_effect_class": "READ_ONLY",
                },
            ])
        tasks: list[dict[str, Any]] = []
        previous: str | None = None
        for index, item in enumerate(functions, start=1):
            task_id = f"task-{index:02d}"
            dependencies = [previous] if previous else []
            tasks.append({
                "task_id": task_id,
                "functional_role": item["function"],
                "task_class": item["task_class"],
                "action": item["action"],
                "query": item["query"],
                "required_capability_description": item[
                    "required_capability_description"
                ],
                "objective": (
                    f"{item['function']}: {goal.human_goal}"
                ),
                "dependencies": dependencies,
                "expected_output": item["expected_output"],
                "acceptance_criteria": item["acceptance_criteria"],
                "risk_side_effect_class": item["risk_side_effect_class"],
            })
            previous = task_id
        return tasks

    if goal.mission_class == "GTA6_INTELLIGENCE":
        functions = [
            (
                "DISCOVER",
                "gta6-research",
                "RESEARCH",
                "GTA6 official source research evidence delta",
                "source-grounded GTA6 evidence discovery",
                "ResearchEvidence",
            ),
            (
                "VERIFY",
                "gta6-fact-check",
                "RESEARCH",
                "GTA6 independent fact check claims evidence",
                "independent GTA6 evidence verification",
                "VerifiedClaims",
            ),
        ]
        if any(
            term in folded
            for term in ("video", "vídeo", "pauta", "roteiro", "rende")
        ):
            functions.append((
                "EDITORIALIZE",
                "youtube-content-strategy",
                "EDITORIAL",
                "youtube content strategy editorial opportunity",
                "editorial opportunity extraction from verified evidence",
                "EditorialOpportunity",
            ))
        tasks = []
        previous = None
        for index, (
            role,
            task_class,
            action,
            query,
            description,
            output,
        ) in enumerate(functions, start=1):
            task_id = f"task-{index:02d}"
            tasks.append({
                "task_id": task_id,
                "functional_role": role,
                "task_class": task_class,
                "action": action,
                "query": query,
                "required_capability_description": description,
                "objective": f"{role}: {goal.human_goal}",
                "dependencies": [previous] if previous else [],
                "expected_output": output,
                "acceptance_criteria": [
                    "evidence lineage preserved",
                    "authority not expanded",
                ],
                "risk_side_effect_class": "READ_ONLY",
            })
            previous = task_id
        return tasks

    if goal.mission_class == "EDITORIAL":
        return [
            {
                "task_id": "task-01",
                "functional_role": "DESIGN",
                "task_class": "youtube-content-strategy",
                "action": "EDITORIAL",
                "query": "youtube content strategy editorial evidence",
                "required_capability_description": (
                    "evidence-grounded editorial strategy"
                ),
                "objective": f"DESIGN: {goal.human_goal}",
                "dependencies": [],
                "expected_output": "EditorialStrategy",
                "acceptance_criteria": ["strategy is evidence-grounded"],
                "risk_side_effect_class": "READ_ONLY",
            },
            {
                "task_id": "task-02",
                "functional_role": "REVIEW",
                "task_class": "youtube-script-review",
                "action": "EDITORIAL",
                "query": "youtube script review quality evidence",
                "required_capability_description": (
                    "independent editorial quality review"
                ),
                "objective": f"REVIEW: {goal.human_goal}",
                "dependencies": ["task-01"],
                "expected_output": "ScriptReview",
                "acceptance_criteria": ["review references strategy evidence"],
                "risk_side_effect_class": "READ_ONLY",
            },
        ]
    return []


def _deterministic_fast_path_requirements(
    goal: GoalEnvelope,
) -> list[dict[str, Any]]:
    """Keep only narrow, high-confidence cases off the semantic provider."""
    folded = re.sub(r"\s+", " ", goal.human_goal.strip().casefold())
    complex_terms = (
        "descobre", "investiga", "sozinho", "regred", "artificial", "estranha",
        "inútil", "inutil", "prova", "especialistas", "agentes", "aprendeu",
        "últimas execuções", "ultimas execucoes", "não sei", "nao sei",
        "qualidade geral", "sem deixar", "carroça", "carroca",
    )
    if any(term in folded for term in complex_terms):
        return []
    if goal.mission_class == "GTA6_INTELLIGENCE" and len(folded) <= 180:
        return _deterministic_capability_requirements(goal)
    if goal.mission_class == "EDITORIAL" and len(folded) <= 140:
        if any(
            term in folded
            for term in ("revisa", "revise", "roteiro", "seo", "thumbnail")
        ):
            return _deterministic_capability_requirements(goal)
    if goal.mission_class == "SYSTEM_IMPROVEMENT" and len(folded) <= 120:
        if any(
            term in folded
            for term in (
                "melhora o sistema",
                "melhore o sistema",
                "otimiza o pipeline",
                "otimize o pipeline",
            )
        ):
            return _deterministic_capability_requirements(goal)
    return []


def _resource_bounds(resources: dict[str, Any]) -> dict[str, int]:
    return {
        key: int(resources[key])
        for key in (
            "max_tasks_per_mission",
            "max_retries_per_task",
            "max_reviewer_loops",
            "max_parallelism",
            "mission_timeout_seconds",
            "bounded_memory_bytes",
        )
    }


def _planning_domain(goal: GoalEnvelope) -> str:
    return {
        "SYSTEM_IMPROVEMENT": "system-improvement",
        "GTA6_INTELLIGENCE": "research",
        "EDITORIAL": "youtube",
        "OPEN_SEMANTIC": "general",
    }.get(goal.mission_class, "general")


def plan_mission_from_human_goal(
    goal: GoalEnvelope,
    *,
    artifact_ref: str | None = None,
    semantic_inference: Callable[[str, dict[str, Any]], str | dict[str, Any]] | None = None,
) -> HarnessMissionPlan:
    policy = load_continuous_operation_policy()
    resources = dict(policy.resource_governance)
    bounds = _resource_bounds(resources)
    health = semantic_provider_health()
    domain = _planning_domain(goal)
    memory = build_bounded_memory_context(
        goal_id=goal.goal_id,
        domain=domain,
        task_class=goal.mission_class.casefold().replace("_", "-"),
        artifact_ref=artifact_ref,
        intent=goal.human_goal,
        max_bytes=int(resources["bounded_memory_bytes"]),
    ).to_dict()
    adaptive_context = build_semantic_planning_context(
        goal=goal.to_dict(),
        bounded_memory_context=memory,
        resource_bounds=bounds,
        provider_health=health,
        artifact_ref=artifact_ref,
    )

    requirements = _deterministic_fast_path_requirements(goal)
    planning_mode = "DETERMINISTIC_FAST_PATH" if requirements else "SEMANTIC_ADAPTIVE"
    proposal = None
    planning_evidence: dict[str, Any] = {
        "planning_mode": planning_mode,
        "semantic_provider_call_count": 0,
        "harness_validated": True,
        "authority": "DEEPSEEK_HARNESS",
        "planner_authority": "NONE",
        "selection": [],
    }
    planning_evidence["context_retrieval"] = dict(
        adaptive_context.get("context_retrieval_evidence") or {}
    )

    if not requirements:
        if not health.get("semantic_reasoning_available") and semantic_inference is None:
            raise RuntimeError("SEMANTIC_REASONING_PROVIDER_UNAVAILABLE")
        semantic_result, semantic_evidence = propose_validated_semantic_plan(
            adaptive_context,
            inference=semantic_inference,
            max_replans=1,
        )
        proposal = semantic_result.proposal
        planning_evidence.update(semantic_evidence)
        planning_evidence["semantic_provider_call_count"] = int(
            semantic_evidence.get("proposal_attempts") or 1
        )
        if proposal.needs_human_clarification:
            raise RuntimeError(
                "MISSION_NEEDS_HUMAN_CLARIFICATION:"
                + str(proposal.clarification_question or "")
            )
        requirements = proposal_requirements(proposal)

    requirements = requirements[: int(resources["max_tasks_per_mission"])]
    if not requirements:
        raise RuntimeError("MISSION_REQUIREMENTS_UNRESOLVED")

    selected_tasks: list[dict[str, Any]] = []
    used: set[str] = set()
    competence_used = False
    avoided_paths: list[str] = []
    proposal_reuse_refs = list(proposal.reused_artifact_refs) if proposal else []

    for requirement in requirements:
        capability_id, used_competence, avoided, selection = (
            select_capability_for_requirement(
                requirement,
                context=adaptive_context,
                used=used,
            )
        )
        selection = {
            **selection,
            "selection_mode": planning_mode,
            "functional_role": requirement.get("functional_role"),
        }
        planning_evidence["selection"].append(selection)
        avoided_paths.extend(avoided)

        competence_used = competence_used or used_competence
        used.add(capability_id)
        input_refs: list[str] = []
        for ref in ([artifact_ref] if artifact_ref else []) + proposal_reuse_refs:
            if ref and ref not in input_refs:
                input_refs.append(ref)
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        selected_tasks.append({
            "task_id": requirement["task_id"],
            "capability_id": capability_id,
            "action": requirement["action"],
            "objective": str(
                requirement.get("objective")
                or f"{goal.human_goal} :: {requirement['task_class']}"
            ),
            "task_class": str(requirement.get("task_class") or "GENERAL"),
            "required_capability_description": str(
                requirement.get("required_capability_description")
                or requirement.get("query")
                or ""
            )[:500],
            "dependencies": requirement["dependencies"],
            "input_refs": input_refs,
            "expected_output": requirement["expected_output"],
            "acceptance_criteria": list(
                requirement.get("acceptance_criteria")
                or [f"produce {requirement['expected_output']}"]
            ),
            "candidate_requirement": str(
                requirement.get("candidate_requirement")
                or (
                    "REQUIRED"
                    if record.default_write_scope
                    else "NOT_APPLICABLE"
                )
            ).upper(),
            "read_scope": list(record.default_read_scope),
            "write_scope": list(record.default_write_scope),
            "allowed_tools": list(record.allowed_tools),
            "allowed_side_effects": list(record.side_effects),
            "forbidden_side_effects": [
                "publication",
                "policy_mutation",
                "authority_mutation",
                "canonical_memory_write",
                "secret_access",
            ],
            "time_budget_seconds": min(
                int(bounds["mission_timeout_seconds"]),
                900,
            ),
            "cost_budget": 0.0,
            "context_budget_bytes": int(bounds["bounded_memory_bytes"]),
            "tool_budget": 32,
            "retry_budget": (
                min(int(bounds["max_retries_per_task"]), 2)
                if record.supports_retry else 0
            ),
            "evidence_contract": str(record.evidence_contract or ""),
            "review_policy": (
                "INDEPENDENT_REQUIRED"
                if record.supports_review and record.default_write_scope
                else "NONE"
            ),
            "risk_side_effect_class": str(
                requirement.get("risk_side_effect_class")
                or record.side_effect_class
                or "READ_ONLY"
            ),
            "human_gate_policy": (
                "POLICY_DEFINED_PROMOTION"
                if record.default_write_scope
                else "NONE"
            ),
        })

    opencode_state = str((health.get("opencode") or {}).get("state") or "")
    if opencode_state in {"UPSTREAM_DENIED", "BLOCKED", "QUARANTINED"}:
        avoided_paths.append("opencode_provider_" + opencode_state.casefold())

    if proposal:
        for item in proposal.avoided_bad_paths:
            if item not in avoided_paths:
                avoided_paths.append(item)

    fingerprint = sha256(json.dumps(
        {
            "goal": goal.to_dict(),
            "planning_mode": planning_mode,
            "proposal": proposal.to_dict() if proposal else None,
            "tasks": selected_tasks,
        },
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

    memory_present = bool(
        memory.get("conversation_memory")
        or memory.get("operational_memory")
        or memory.get("knowledge_memory")
        or memory.get("artifact_lineage_memory")
    )
    memory_influences = bool(
        proposal
        and memory_present
        and (
            proposal.memory_strategy_notes
            or proposal.reused_artifact_refs
            or proposal.avoided_bad_paths
            or avoided_paths
        )
    )
    gates: list[str] = []
    if any(
        item.get("write_scope")
        and str(item.get("review_policy") or "") == "INDEPENDENT_REQUIRED"
        for item in selected_tasks
    ):
        gates.append("promotion")
    if proposal and any(
        task.risk_side_effect_class in {"HIGH", "EXTERNAL_SIDE_EFFECT"}
        for task in proposal.tasks
    ):
        gates.append("human-side-effect-approval")

    planning_evidence["memory_context_present"] = memory_present
    planning_evidence["memory_influences_strategy"] = memory_influences
    planning_evidence["competence_influences_selection"] = competence_used
    planning_evidence["known_bad_paths_avoided"] = list(dict.fromkeys(avoided_paths))

    return HarnessMissionPlan(
        mission_id=mission_id,
        plan_id=plan_id,
        goal=goal,
        collaboration_plan=collaboration,
        bounded_memory_context=memory,
        resource_bounds=bounds,
        provider_health=health,
        selected_by_competence=competence_used,
        known_bad_paths_avoided=tuple(dict.fromkeys(avoided_paths)),
        human_gates=tuple(dict.fromkeys(gates)),
        planning_mode=planning_mode,
        semantic_plan_proposal=proposal.to_dict() if proposal else None,
        planning_evidence=planning_evidence,
        memory_influences_strategy=memory_influences,
        competence_influences_selection=competence_used,
    )
