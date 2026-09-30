from __future__ import annotations

from app.services.capability_health_service import CapabilityHealth
from app.services.global_capability_registry_base import CapabilityRecord
from app.services.harness_worker_scheduler import CandidateDecision
from app.services.harness_agent_fleet_projection_service import (
    build_agent_capability_profile,
    project_capability_maturity,
)


def _record(**overrides):
    base=dict(
        capability_id="test.analysis",
        capability_type="AGENT",
        domain="system",
        implementation="tests.Fake",
        input_contract="TaskExecutionEnvelope/v1",
        output_contract="TaskExecutionEvidence/v1",
        requirements=(),
        maturity="FUNCTIONAL",
        availability="AVAILABLE",
        allowed_actions=("DECISION",),
        policy_tags=("system",),
        security_boundary="read only",
        cost_class="ZERO_COST",
        quota_class="LOCAL",
        latency_class="LOW",
        quality_class="HIGH",
        evidence_contract="TaskExecutionEvidence/v1",
        fallback_eligibility=False,
        executor_binding="tests.fake.execute",
        version="1",
        agent_id="agent-test",
        side_effect_class="READ_ONLY",
        default_read_scope=("repository",),
        default_write_scope=(),
        allowed_tools=("repository.read",),
        supports_parallelism=True,
        supports_retry=True,
        supports_resume=True,
        supports_review=False,
        execution_kind="SEMANTIC_REASONER",
        functional_roles=("DIAGNOSIS",),
        execution_operations=("READ",),
    )
    base.update(overrides)
    return CapabilityRecord(**base)


def _health(state="HEALTHY", refs=("artifact:health.json",)):
    return CapabilityHealth(
        capability_id="test.analysis",
        state=state,
        reason="test health",
        retry_allowed=state in {"HEALTHY", "DEGRADED"},
        confidence=1.0,
        sample_size=1,
        last_success_at="2026-09-29T00:00:00+00:00" if state=="HEALTHY" else None,
        last_failure_at=None,
        evidence_refs=refs,
        source="TEST",
    )


def test_available_functional_record_is_not_evidence_bound_proven_or_eligible():
    snapshot=project_capability_maturity(
        record=_record(),
        health=_health(),
        runtime_proof_refs=(),
        task_candidate_decision=None,
    )
    assert snapshot.discovered is True
    assert snapshot.registered is True
    assert snapshot.executable is True
    assert snapshot.healthy is True
    assert snapshot.registry_maturity == "FUNCTIONAL"
    assert snapshot.proven is False
    assert snapshot.eligible is False


def test_static_proven_but_blocked_health_is_not_healthy_or_eligible():
    snapshot=project_capability_maturity(
        record=_record(maturity="PROVEN"),
        health=_health(state="BLOCKED", refs=("artifact:failure.json",)),
        runtime_proof_refs=("artifact:runtime-proof.json",),
        task_candidate_decision=CandidateDecision("worker:test",True,"ACCEPTED"),
    )
    assert snapshot.proven is True
    assert snapshot.healthy is False
    assert snapshot.eligible is False


def test_evidence_bound_proven_healthy_and_worker_accepted_is_eligible():
    snapshot=project_capability_maturity(
        record=_record(maturity="PROVEN"),
        health=_health(),
        runtime_proof_refs=("artifact:runtime-proof.json",),
        task_candidate_decision=CandidateDecision("worker:test",True,"ACCEPTED"),
    )
    assert snapshot.proven is True
    assert snapshot.eligible is True
    assert "artifact:runtime-proof.json" in snapshot.evidence_refs


def test_high_quality_metadata_cannot_bypass_hard_eligibility_rejection():
    snapshot=project_capability_maturity(
        record=_record(maturity="PROVEN", quality_class="VERY_HIGH"),
        health=_health(),
        runtime_proof_refs=("artifact:runtime-proof.json",),
        task_candidate_decision=CandidateDecision(
            "worker:test",False,"SIDE_EFFECT_CLASS_MISMATCH"
        ),
    )
    assert snapshot.eligible is False
    assert "SIDE_EFFECT_CLASS_MISMATCH" in snapshot.reasons


def test_executable_requires_binding_contracts_and_available_metadata():
    snapshot=project_capability_maturity(
        record=_record(executor_binding=None),
        health=_health(),
        runtime_proof_refs=("artifact:runtime-proof.json",),
        task_candidate_decision=None,
    )
    assert snapshot.executable is False
    assert snapshot.proven is False
    assert snapshot.eligible is False


def test_profile_is_projection_over_registry_and_health_not_new_authority():
    record=_record(maturity="PROVEN")
    health=_health()
    maturity=project_capability_maturity(
        record=record,
        health=health,
        runtime_proof_refs=("artifact:runtime-proof.json",),
        task_candidate_decision=CandidateDecision("worker:test",True,"ACCEPTED"),
    )
    profile=build_agent_capability_profile(
        record=record,
        health=health,
        maturity=maturity,
        runtime_family="AGENT_OFFICE",
        runtime_proof_ref="artifact:runtime-proof.json",
        independence_group="codex",
        context_budget=32768,
        tool_budget=16,
        time_budget=300,
    )
    assert profile.capability_id == record.capability_id
    assert profile.agent_id == record.agent_id
    assert profile.runtime_family == "AGENT_OFFICE"
    assert profile.executor_binding == record.executor_binding
    assert profile.maturity.eligible is True
    assert profile.authority_source == "GLOBAL_CAPABILITY_REGISTRY+HARNESS_POLICY"


def test_profile_rejects_harness_only_functional_role():
    record=_record(functional_roles=("REDUCTION",),maturity="PROVEN")
    health=_health()
    maturity=project_capability_maturity(
        record=record,
        health=health,
        runtime_proof_refs=("artifact:runtime-proof.json",),
        task_candidate_decision=CandidateDecision("worker:test",True,"ACCEPTED"),
    )
    import pytest
    with pytest.raises(ValueError, match="Harness-only"):
        build_agent_capability_profile(
            record=record,
            health=health,
            maturity=maturity,
            runtime_family="AGENT_OFFICE",
            runtime_proof_ref="artifact:runtime-proof.json",
            independence_group="codex",
            context_budget=32768,
            tool_budget=16,
            time_budget=300,
        )
