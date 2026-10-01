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


MAX_PARALLEL_CODEX_WORKERS = 2
_PARALLEL_TOPOLOGIES = {"PARALLEL_INDEPENDENT", "PARALLEL_WITH_REDUCTION", "HYBRID"}


@dataclass(frozen=True)
class EffectiveParallelismDecision:
    effective_parallelism: int
    subagent_count: int
    serialized_for_conflict: bool
    limit_source: str
    schema: str = "EffectiveParallelismDecision/v1"


def effective_parallelism(
    *,
    topology: TaskTopologyAssessment,
    topology_safe_parallelism: int,
    conflict_safe_parallelism: int,
    execution_budget: int,
    runtime_allowance: int,
    empirically_proven_parallelism: int,
) -> EffectiveParallelismDecision:
    values = (
        topology_safe_parallelism,
        conflict_safe_parallelism,
        execution_budget,
        runtime_allowance,
        empirically_proven_parallelism,
    )
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
        raise ValueError("parallelism inputs must be non-negative integers")
    name = str(topology.topology or "").upper()
    conflict = bool(
        topology.evidence.get("write_set_overlap")
        or topology.evidence.get("shared_mutable_state")
        or conflict_safe_parallelism <= 1
    )
    if name not in _PARALLEL_TOPOLOGIES or conflict:
        return EffectiveParallelismDecision(
            effective_parallelism=1,
            subagent_count=0,
            serialized_for_conflict=conflict,
            limit_source="TASK_TOPOLOGY_OR_CONFLICT",
        )
    effective = min(
        MAX_PARALLEL_CODEX_WORKERS,
        topology_safe_parallelism,
        conflict_safe_parallelism,
        execution_budget,
        runtime_allowance,
        empirically_proven_parallelism,
    )
    effective = max(1, effective)
    return EffectiveParallelismDecision(
        effective_parallelism=effective,
        subagent_count=effective if effective > 1 else 0,
        serialized_for_conflict=False,
        limit_source="MAX_PARALLEL_CODEX_WORKERS" if effective == MAX_PARALLEL_CODEX_WORKERS else "LOWER_BOUND",
    )
