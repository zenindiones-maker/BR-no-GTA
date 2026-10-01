from __future__ import annotations

import pytest

from app.services.harness_coalition_execution_service import (
    CoalitionTask,
    build_coalition_waves,
)
from app.services.harness_improvement_coalition_service import (
    AgentEffortBudget,
    TaskTopologyAssessment,
)


def _topology(name):
    return TaskTopologyAssessment(
        topology=name,
        reasons=("test",),
        evidence={},
    )


def test_sequential_topology_never_fans_out():
    tasks=(
        CoalitionTask("diagnose",(),(),("artifact:input",),"RootCauseEvidence/v1","DIAGNOSIS",False),
        CoalitionTask("apply",("diagnose",),("app/x.py",),("artifact:diagnosis",),"PatchCandidate/v1","APPLY",True),
        CoalitionTask("review",("apply",),(),("artifact:patch",),"ReviewEvidence/v1","INDEPENDENT_REVIEW",False),
    )
    waves=build_coalition_waves(
        topology=_topology("SEQUENTIAL"),
        tasks=tasks,
        effort_budget=AgentEffortBudget.for_complexity("COMPLEX"),
    )
    assert [len(w.assigned_task_ids) for w in waves] == [1,1,1]
    assert all(w.fan_in_policy=="HARNESS_REDUCER" for w in waves)


def test_parallel_independent_uses_bounded_fanout():
    tasks=tuple(
        CoalitionTask(f"research-{i}",(),(),("artifact:input",),"ResearchEvidence/v1","RESEARCH",False)
        for i in range(5)
    )
    budget=AgentEffortBudget.for_complexity("COMPLEX")
    waves=build_coalition_waves(
        topology=_topology("PARALLEL_INDEPENDENT"),
        tasks=tasks,
        effort_budget=budget,
    )
    assert max(len(w.assigned_task_ids) for w in waves) <= budget.max_agents
    assert len(waves[0].assigned_task_ids) == budget.max_agents
    assert waves[0].fan_in_policy=="HARNESS_REDUCER"


def test_parallel_group_rejects_dependency_edge():
    tasks=(
        CoalitionTask("a",(),(),(),"ResearchEvidence/v1","RESEARCH",False),
        CoalitionTask("b",("a",),(),(),"ResearchEvidence/v1","RESEARCH",False),
    )
    waves=build_coalition_waves(
        topology=_topology("PARALLEL_INDEPENDENT"),
        tasks=tasks,
        effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
    )
    assert [tuple(w.assigned_task_ids) for w in waves] == [("a",),("b",)]


def test_mutating_tasks_with_overlap_are_never_same_parallel_wave():
    tasks=(
        CoalitionTask("a",(),("app",),(),"PatchCandidate/v1","APPLY",True),
        CoalitionTask("b",(),("app/x.py",),(),"PatchCandidate/v1","APPLY",True),
    )
    waves=build_coalition_waves(
        topology=_topology("HYBRID"),
        tasks=tasks,
        effort_budget=AgentEffortBudget.for_complexity("COMPLEX"),
    )
    assert all(len(w.assigned_task_ids)==1 for w in waves)


def test_handoffs_are_artifact_first_and_never_raw_transcripts():
    task=CoalitionTask(
        "review",(),(),("artifact:patch:sha256:abc",),
        "ReviewEvidence/v1","INDEPENDENT_REVIEW",False,
    )
    wave=build_coalition_waves(
        topology=_topology("SINGLE_AGENT"),
        tasks=(task,),
        effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
    )[0]
    assert wave.input_artifact_refs == ("artifact:patch:sha256:abc",)
    assert wave.raw_transcript_refs == ()
    assert wave.fan_in_policy=="HARNESS_REDUCER"


def test_harness_only_reduction_is_not_assignable_task_role():
    task=CoalitionTask("bad",(),(),(),"ReductionEvidence/v1","REDUCTION",False)
    with pytest.raises(ValueError, match="Harness-only"):
        build_coalition_waves(
            topology=_topology("SINGLE_AGENT"),
            tasks=(task,),
            effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
        )

def test_effective_parallelism_caps_codex_workers_at_two_and_sequential_has_no_subagents():
    from app.services.harness_coalition_execution_service import effective_parallelism
    parallel=effective_parallelism(
        topology=_topology("PARALLEL_INDEPENDENT"),
        topology_safe_parallelism=5,
        conflict_safe_parallelism=4,
        execution_budget=4,
        runtime_allowance=8,
        empirically_proven_parallelism=3,
    )
    assert parallel.effective_parallelism==2
    assert parallel.subagent_count==2
    assert parallel.limit_source=="MAX_PARALLEL_CODEX_WORKERS"

    sequential=effective_parallelism(
        topology=_topology("SEQUENTIAL"),
        topology_safe_parallelism=1,
        conflict_safe_parallelism=1,
        execution_budget=4,
        runtime_allowance=8,
        empirically_proven_parallelism=3,
    )
    assert sequential.effective_parallelism==1
    assert sequential.subagent_count==0


def test_effective_parallelism_serializes_write_conflict():
    from app.services.harness_coalition_execution_service import effective_parallelism
    decision=effective_parallelism(
        topology=TaskTopologyAssessment(
            topology="HYBRID",
            reasons=("write-overlap",),
            evidence={"write_set_overlap":True,"shared_mutable_state":False},
        ),
        topology_safe_parallelism=2,
        conflict_safe_parallelism=1,
        execution_budget=2,
        runtime_allowance=2,
        empirically_proven_parallelism=2,
    )
    assert decision.effective_parallelism==1
    assert decision.subagent_count==0
    assert decision.serialized_for_conflict is True
