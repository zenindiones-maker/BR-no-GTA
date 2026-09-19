from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

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
                learning_required=False,
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
