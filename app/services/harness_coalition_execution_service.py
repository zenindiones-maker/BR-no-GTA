from __future__ import annotations

from dataclasses import dataclass

from app.services.harness_improvement_coalition_service import (
    AgentEffortBudget,
    TaskTopologyAssessment,
)


_HARNESS_ONLY_ROLES = {"MISSION_AUTHORITY", "REDUCTION", "PROMOTION"}


@dataclass(frozen=True)
class CoalitionTask:
    task_id: str
    dependency_task_ids: tuple[str, ...]
    write_set: tuple[str, ...]
    input_artifact_refs: tuple[str, ...]
    expected_output_contract: str
    functional_role: str
    mutation_required: bool


@dataclass(frozen=True)
class CoalitionWave:
    wave_id: str
    assigned_task_ids: tuple[str, ...]
    input_artifact_refs: tuple[str, ...]
    expected_result_contracts: tuple[str, ...]
    raw_transcript_refs: tuple[str, ...]
    fan_in_policy: str = "HARNESS_REDUCER"
    schema: str = "CoalitionWave/v1"


def _paths_overlap(a: str, b: str) -> bool:
    left = str(a).strip("/")
    right = str(b).strip("/")
    if not left or not right:
        return False
    return (
        left == right
        or left.startswith(right + "/")
        or right.startswith(left + "/")
    )


def _can_share_wave(
    task: CoalitionTask,
    current: list[CoalitionTask],
    completed: set[str],
) -> bool:
    if any(dep not in completed for dep in task.dependency_task_ids):
        return False
    for other in current:
        if task.task_id in other.dependency_task_ids:
            return False
        if other.task_id in task.dependency_task_ids:
            return False
        if task.mutation_required or other.mutation_required:
            for left in task.write_set:
                for right in other.write_set:
                    if _paths_overlap(left, right):
                        return False
    return True


def _wave_from_tasks(index: int, tasks: list[CoalitionTask]) -> CoalitionWave:
    refs = tuple(dict.fromkeys(
        ref
        for task in tasks
        for ref in task.input_artifact_refs
        if str(ref).strip()
    ))
    contracts = tuple(task.expected_output_contract for task in tasks)
    return CoalitionWave(
        wave_id=f"wave-{index:03d}",
        assigned_task_ids=tuple(task.task_id for task in tasks),
        input_artifact_refs=refs,
        expected_result_contracts=contracts,
        raw_transcript_refs=(),
    )


def build_coalition_waves(
    *,
    topology: TaskTopologyAssessment,
    tasks: tuple[CoalitionTask, ...],
    effort_budget: AgentEffortBudget,
) -> tuple[CoalitionWave, ...]:
    for task in tasks:
        role = str(task.functional_role or "").upper()
        if role in _HARNESS_ONLY_ROLES:
            raise ValueError("Harness-only functional role cannot be assigned")

    pending = list(tasks)
    completed: set[str] = set()
    waves: list[CoalitionWave] = []
    max_parallel = max(1, int(effort_budget.max_agents))

    sequential_topologies = {"SINGLE_AGENT", "SEQUENTIAL", "MAKER_CHECKER"}
    while pending:
        if topology.topology in sequential_topologies:
            chosen = None
            for task in pending:
                if all(dep in completed for dep in task.dependency_task_ids):
                    chosen = task
                    break
            if chosen is None:
                raise RuntimeError("UNRESOLVED_TASK_DEPENDENCY")
            group = [chosen]
        else:
            group: list[CoalitionTask] = []
            for task in pending:
                if len(group) >= max_parallel:
                    break
                if _can_share_wave(task, group, completed):
                    group.append(task)
            if not group:
                # A dependency chain exists. Serialize the next ready task rather
                # than creating an invalid parallel group.
                chosen = next(
                    (
                        task for task in pending
                        if all(dep in completed for dep in task.dependency_task_ids)
                    ),
                    None,
                )
                if chosen is None:
                    raise RuntimeError("UNRESOLVED_TASK_DEPENDENCY")
                group = [chosen]

        wave = _wave_from_tasks(len(waves) + 1, group)
        waves.append(wave)
        for task in group:
            pending.remove(task)
            completed.add(task.task_id)

    return tuple(waves)
