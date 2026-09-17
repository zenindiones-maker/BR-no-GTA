from __future__ import annotations

from app.services.gta6_fact_check_service import (
    FACT_CHECK_CAPABILITY_ID,
    FACT_CHECK_EXECUTOR_BINDING,
)
from app.services.swarm_execution_proof_service import (
    AgentInvocationReceipt,
    CapabilityCoverageMatrix,
    SwarmMissionProof,
)


def _fact_check_receipt() -> AgentInvocationReceipt:
    return AgentInvocationReceipt(
        mission_id="mission-fact-check-proof",
        task_id="task-fact-check-proof",
        goal_id="goal-fact-check-proof",
        decision_id="decision-fact-check-proof",
        authorization_id="authorization-fact-check-proof",
        agent_id="gta6-fact-check",
        skill_id="gta6-fact-check",
        capability=FACT_CHECK_CAPABILITY_ID,
        executor=FACT_CHECK_EXECUTOR_BINDING,
        provider="internal",
        input_refs=("claim:fact-check-proof",),
        output_refs=("fact-check:mission-fact-check-proof:task-fact-check-proof",),
        evidence_refs=("source:rockstar-newswire:proof",),
        started_at="2026-09-17T18:00:00+00:00",
        finished_at="2026-09-17T18:00:01+00:00",
        status="COMPLETED",
        validation_level="LIVE",
        external_call_performed=False,
        exit_code=0,
        returned_to_harness=True,
    )


def test_fact_check_live_receipt_derives_proven_live_coverage():
    receipt = _fact_check_receipt()
    matrix = CapabilityCoverageMatrix.derive(
        mission_id=receipt.mission_id,
        capability_ids=(FACT_CHECK_CAPABILITY_ID,),
        receipts=(receipt,),
        consumers={FACT_CHECK_CAPABILITY_ID: ("deepseek_harness",)},
    )

    assert receipt.proven_live is True
    assert matrix.all_proven_live is True
    assert len(matrix.entries) == 1
    entry = matrix.entries[0]
    assert entry.capability == FACT_CHECK_CAPABILITY_ID
    assert entry.invoked is True
    assert entry.live is True
    assert entry.returned_to_harness is True
    assert entry.status == "PROVEN_LIVE"
    assert entry.consumed_by == ("deepseek_harness",)


def test_fact_check_receipt_enters_mission_proof_without_faking_e2e_completion():
    receipt = _fact_check_receipt()
    proof = SwarmMissionProof(
        mission_id=receipt.mission_id,
        goal_id=receipt.goal_id,
        harness_decision_id=receipt.decision_id,
        authorization_id=receipt.authorization_id,
        plan_ref="plan:fact-check-proof",
        task_graph_ref="task-graph:fact-check-proof",
        receipts=(receipt,),
        publication_gate_ref="gate:br_youtube_pode_postar",
        publication_attempted=False,
        job18_state_before="frozen",
        job18_state_after="frozen",
        job20_reused_as_final=False,
        review_state="FACT_CHECK_COMPLETE",
    )

    serialized = proof.to_dict()
    assert proof.live_invocation_proven is True
    assert serialized["agent_invocation_receipts"][0]["capability"] == FACT_CHECK_CAPABILITY_ID
    assert serialized["agent_invocation_receipts"][0]["executor"] == FACT_CHECK_EXECUTOR_BINDING
    assert proof.job18_unchanged is True
    assert proof.publication_gate_preserved is True
    assert proof.end_to_end_synergy_passed is False
