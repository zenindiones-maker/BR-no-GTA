import pytest

from app.services.swarm_execution_proof_service import (
    AgentInvocationReceipt,
    CapabilityCoverageMatrix,
    SwarmMissionProof,
    SwarmTask,
    SwarmTaskGraph,
)


def _live_receipt(**overrides):
    values = {
        "mission_id": "mission-1",
        "task_id": "research-1",
        "goal_id": "goal-1",
        "decision_id": "decision-1",
        "authorization_id": "auth-1",
        "agent_id": "gta6-research",
        "capability": "gta6.research.fresh-cloud",
        "executor": "fresh-research-executor",
        "provider": "internal",
        "input_refs": ("telegram:10",),
        "output_refs": ("research:1",),
        "evidence_refs": ("evidence:1",),
        "started_at": "2026-09-17T12:00:00+00:00",
        "finished_at": "2026-09-17T12:00:01+00:00",
        "status": "COMPLETED",
        "validation_level": "LIVE",
        "external_call_performed": True,
        "exit_code": 0,
        "latency_seconds": 1.0,
        "returned_to_harness": True,
    }
    values.update(overrides)
    return AgentInvocationReceipt(**values)


def test_completed_receipt_requires_output_evidence_and_harness_return():
    with pytest.raises(ValueError, match="evidence_refs"):
        _live_receipt(evidence_refs=())
    with pytest.raises(ValueError, match="output_refs"):
        _live_receipt(output_refs=())
    with pytest.raises(ValueError, match="return to Harness"):
        _live_receipt(returned_to_harness=False)


def test_live_receipt_is_not_conflated_with_structural_proof():
    live = _live_receipt()
    structural = _live_receipt(
        task_id="research-structural",
        validation_level="STRUCTURAL",
        external_call_performed=False,
    )
    assert live.proven_live is True
    assert live.proven_structural is False
    assert structural.proven_live is False
    assert structural.proven_structural is True


def test_task_graph_enforces_dependencies_and_detects_cycles():
    graph = SwarmTaskGraph(
        mission_id="mission-1",
        tasks=(
            SwarmTask(task_id="research", capability="gta6.research", agent_id="research"),
            SwarmTask(
                task_id="fact-check",
                capability="gta6.fact-check",
                agent_id="fact-check",
                dependencies=("research",),
            ),
        ),
    )
    assert graph.ready_task_ids(()) == ("research",)
    assert graph.ready_task_ids(("research",)) == ("fact-check",)

    with pytest.raises(ValueError, match="cycle"):
        SwarmTaskGraph(
            mission_id="mission-cycle",
            tasks=(
                SwarmTask(task_id="a", capability="a", agent_id="a", dependencies=("b",)),
                SwarmTask(task_id="b", capability="b", agent_id="b", dependencies=("a",)),
            ),
        )


def test_coverage_matrix_is_derived_from_receipts_not_registry_presence():
    receipt = _live_receipt()
    matrix = CapabilityCoverageMatrix.derive(
        mission_id="mission-1",
        capability_ids=(
            "gta6.research.fresh-cloud",
            "gta6.fact-check",
            "higgsfield-generate",
        ),
        receipts=(receipt,),
        structurally_proven=("gta6.fact-check",),
        external_blocked=("higgsfield-generate",),
        consumers={"gta6.research.fresh-cloud": ("gta6.fact-check",)},
    )
    states = {entry.capability: entry.status for entry in matrix.entries}
    assert states == {
        "gta6.research.fresh-cloud": "PROVEN_LIVE",
        "gta6.fact-check": "PROVEN_STRUCTURAL",
        "higgsfield-generate": "DEGRADED_EXTERNAL_BLOCKER",
    }
    assert matrix.all_proven_live is False


def test_end_to_end_pass_is_derived_from_real_evidence_fields():
    receipt = _live_receipt()
    incomplete = SwarmMissionProof(
        mission_id="mission-1",
        goal_id="goal-1",
        harness_decision_id="decision-1",
        authorization_id="auth-1",
        plan_ref="plan:1",
        task_graph_ref="task-graph:1",
        receipts=(receipt,),
        publication_gate_ref="publication-gate:1",
        publication_attempted=False,
        job18_state_before="frozen",
        job18_state_after="frozen",
    )
    assert incomplete.end_to_end_synergy_passed is False

    complete = SwarmMissionProof(
        mission_id="mission-1",
        goal_id="goal-1",
        harness_decision_id="decision-1",
        authorization_id="auth-1",
        plan_ref="plan:1",
        task_graph_ref="task-graph:1",
        receipts=(receipt,),
        qa_result_ref="qa:1",
        qa_passed=True,
        render_job_id=99,
        video_id=42,
        artifact_ref="artifact:99",
        mp4_sha256="a" * 64,
        telegram_ingress_ref="telegram:ingress:1",
        telegram_delivery_ref="telegram:delivery:1",
        knowledge_return_ref="knowledge:event:1",
        publication_gate_ref="publication-gate:1",
        publication_attempted=False,
        job18_state_before="frozen",
        job18_state_after="frozen",
        job20_reused_as_final=False,
        review_state="READY_FOR_HUMAN_REVIEW",
    )
    assert complete.job18_unchanged is True
    assert complete.publication_gate_preserved is True
    assert complete.telegram_roundtrip_proven is True
    assert complete.render_proven is True
    assert complete.end_to_end_synergy_passed is True
