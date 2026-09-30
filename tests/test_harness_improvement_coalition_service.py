from __future__ import annotations

from dataclasses import replace

from app.services.capability_health_service import CapabilityHealth
from app.services.global_capability_registry_base import CapabilityRecord
from app.services.harness_agent_fleet_projection_service import (
    build_agent_capability_profile,
    project_capability_maturity,
)
from app.services.harness_improvement_coalition_service import (
    AgentEffortBudget,
    TaskTopologyInput,
    assess_task_topology,
    build_improvement_coalition_plan,
)
from app.services.harness_worker_scheduler import CandidateDecision


def _record(capability_id, agent_id, roles, *, supports_review=False):
    return CapabilityRecord(
        capability_id=capability_id,
        capability_type="AGENT",
        domain="system",
        implementation="tests.Fake",
        input_contract="TaskExecutionEnvelope/v1",
        output_contract="TaskExecutionEvidence/v1",
        requirements=(),
        maturity="PROVEN",
        availability="AVAILABLE",
        allowed_actions=("DECISION",),
        policy_tags=("system",),
        security_boundary="bounded",
        cost_class="ZERO_COST",
        quota_class="LOCAL",
        latency_class="LOW",
        quality_class="HIGH",
        evidence_contract="TaskExecutionEvidence/v1",
        fallback_eligibility=False,
        executor_binding=f"tests.{agent_id}.execute",
        version="1",
        agent_id=agent_id,
        side_effect_class="READ_ONLY",
        default_read_scope=("repository",),
        default_write_scope=(),
        allowed_tools=("repository.read",),
        supports_parallelism=True,
        supports_retry=True,
        supports_resume=True,
        supports_review=supports_review,
        execution_kind="SEMANTIC_REASONER",
        functional_roles=tuple(roles),
        execution_operations=("READ",),
    )


def _profile(
    capability_id,
    agent_id,
    roles,
    *,
    eligible=True,
    independence_group=None,
    supports_review=False,
    metrics=None,
):
    record=_record(capability_id,agent_id,roles,supports_review=supports_review)
    health=CapabilityHealth(
        capability_id=capability_id,
        state="HEALTHY",
        reason="ok",
        retry_allowed=True,
        confidence=1.0,
        sample_size=10,
        last_success_at="2026-09-29T00:00:00+00:00",
        last_failure_at=None,
        evidence_refs=(f"artifact:{capability_id}:health",),
        source="TEST",
    )
    decision=CandidateDecision(
        f"worker:{capability_id}",
        eligible,
        "ACCEPTED" if eligible else "POLICY_DENIED",
    )
    maturity=project_capability_maturity(
        record=record,
        health=health,
        runtime_proof_refs=(f"artifact:{capability_id}:proof",),
        task_candidate_decision=decision,
    )
    profile=build_agent_capability_profile(
        record=record,
        health=health,
        maturity=maturity,
        runtime_family="TEST_RUNTIME",
        runtime_proof_ref=f"artifact:{capability_id}:proof",
        independence_group=independence_group or agent_id,
        context_budget=32768,
        tool_budget=16,
        time_budget=300,
    )
    return profile, (metrics or {
        "task_class_competence":80,
        "domain_competence":80,
        "verified_success_rate":80,
        "review_accept_rate":80,
        "health_score":100,
        "latency_efficiency":70,
        "cost_efficiency":80,
        "tool_efficiency":75,
        "context_efficiency":75,
        "failure_penalty":0,
        "critical_regression_penalty":0,
        "human_correction_penalty":0,
        "freshness":90,
    })


def _topology(**overrides):
    base=dict(
        required_roles=("DIAGNOSIS",),
        dependency_density=0.0,
        parallelizable_branch_count=1,
        shared_mutable_state=False,
        tool_count=2,
        write_set_overlap=False,
        context_coupling=0.1,
        risk_class="LOW",
        need_for_independence=False,
        estimated_coordination_overhead=0.1,
        mutation_required=False,
        durable_coordination_required=False,
        reduction_required=False,
    )
    base.update(overrides)
    return assess_task_topology(TaskTopologyInput(**base))


def test_topology_single_agent_and_sequential_are_distinct():
    assert _topology().topology == "SINGLE_AGENT"
    assert _topology(
        required_roles=("DIAGNOSIS","APPLY"),
        dependency_density=0.9,
        shared_mutable_state=True,
        write_set_overlap=True,
        mutation_required=True,
    ).topology == "SEQUENTIAL"


def test_topology_hybrid_for_parallel_analysis_then_serial_mutation():
    assessment=_topology(
        required_roles=("DIAGNOSIS","RESEARCH","APPLY","INDEPENDENT_REVIEW"),
        dependency_density=0.4,
        parallelizable_branch_count=3,
        shared_mutable_state=True,
        write_set_overlap=True,
        need_for_independence=True,
        mutation_required=True,
        reduction_required=True,
        risk_class="HIGH",
    )
    assert assessment.topology == "HYBRID"
    assert assessment.evidence["parallelizable_branch_count"] == 3


def test_minimum_covering_coalition_beats_larger_equivalent_team():
    combo,combo_metrics=_profile(
        "combo","agent-combo",("DIAGNOSIS","RESEARCH"),
        metrics={"task_class_competence":60}
    )
    diagnosis,dm=_profile("diag","agent-d",("DIAGNOSIS",),metrics={"task_class_competence":100})
    research,rm=_profile("research","agent-r",("RESEARCH",),metrics={"task_class_competence":100})
    plan=build_improvement_coalition_plan(
        mission_id="m",
        task_id="t",
        required_roles=("DIAGNOSIS","RESEARCH"),
        topology=_topology(required_roles=("DIAGNOSIS","RESEARCH"),parallelizable_branch_count=2),
        candidates=((combo,combo_metrics),(diagnosis,dm),(research,rm)),
        effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
    )
    assert plan.selected_capability_ids == ("combo",)
    assert plan.agents_selected == 1


def test_adding_irrelevant_agents_does_not_increase_coalition():
    diag,dm=_profile("diag","agent-d",("DIAGNOSIS",))
    base=((diag,dm),)
    irrelevant=tuple(
        _profile(f"irrelevant-{i}",f"agent-{i}",("BENCHMARK",))
        for i in range(20)
    )
    p1=build_improvement_coalition_plan(
        mission_id="m",task_id="t",required_roles=("DIAGNOSIS",),
        topology=_topology(),candidates=base,
        effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
    )
    p2=build_improvement_coalition_plan(
        mission_id="m",task_id="t",required_roles=("DIAGNOSIS",),
        topology=_topology(),candidates=base+irrelevant,
        effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
    )
    assert p1.selected_capability_ids == p2.selected_capability_ids == ("diag",)
    assert p2.agents_considered == 21
    assert p2.agents_selected == 1


def test_ineligible_high_score_is_rejected_before_scoring():
    good,gm=_profile("good","agent-good",("DIAGNOSIS",))
    bad,bm=_profile(
        "bad","agent-bad",("DIAGNOSIS",),eligible=False,
        metrics={"task_class_competence":1000000}
    )
    plan=build_improvement_coalition_plan(
        mission_id="m",task_id="t",required_roles=("DIAGNOSIS",),
        topology=_topology(),candidates=((good,gm),(bad,bm)),
        effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
    )
    assert plan.selected_capability_ids == ("good",)
    assert any(x["capability_id"]=="bad" and x["reason"]=="HARD_INELIGIBLE" for x in plan.rejected_candidates)


def test_maker_and_reviewer_cannot_be_same_agent():
    maker,m1=_profile("maker","agent-same",("APPLY",))
    reviewer,m2=_profile("review","agent-same",("INDEPENDENT_REVIEW",),supports_review=True)
    import pytest
    with pytest.raises(RuntimeError, match="INDEPENDENCE"):
        build_improvement_coalition_plan(
            mission_id="m",task_id="t",
            required_roles=("APPLY","INDEPENDENT_REVIEW"),
            topology=_topology(
                required_roles=("APPLY","INDEPENDENT_REVIEW"),
                mutation_required=True,need_for_independence=True,
            ),
            candidates=((maker,m1),(reviewer,m2)),
            effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
        )


def test_same_backend_distinct_agents_are_allowed_but_limitation_recorded():
    maker,m1=_profile("maker","agent-maker",("APPLY",),independence_group="same-backend")
    reviewer,m2=_profile(
        "review","agent-review",("INDEPENDENT_REVIEW",),
        independence_group="same-backend",supports_review=True
    )
    plan=build_improvement_coalition_plan(
        mission_id="m",task_id="t",
        required_roles=("APPLY","INDEPENDENT_REVIEW"),
        topology=_topology(
            required_roles=("APPLY","INDEPENDENT_REVIEW"),
            mutation_required=True,need_for_independence=True,
        ),
        candidates=((maker,m1),(reviewer,m2)),
        effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
    )
    assert plan.same_backend_independence_limitation is True
    assert set(plan.selected_capability_ids)=={"maker","review"}


def test_identical_snapshot_produces_identical_plan():
    a,am=_profile("a","agent-a",("DIAGNOSIS",))
    b,bm=_profile("b","agent-b",("DIAGNOSIS",))
    kwargs=dict(
        mission_id="m",task_id="t",required_roles=("DIAGNOSIS",),
        topology=_topology(),candidates=((a,am),(b,bm)),
        effort_budget=AgentEffortBudget.for_complexity("STANDARD"),
    )
    assert build_improvement_coalition_plan(**kwargs).selected_capability_ids == build_improvement_coalition_plan(**kwargs).selected_capability_ids


def test_trivial_effort_budget_forbids_agent_storm():
    budget=AgentEffortBudget.for_complexity("TRIVIAL")
    assert budget.max_agents == 1
    assert budget.max_subagents == 0
    assert budget.max_depth == 1
