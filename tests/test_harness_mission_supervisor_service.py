from app.services.harness_mission_supervisor_service import (
    HarnessMissionState,
    HarnessMissionSupervisor,
)


def _supervisor(tmp_path):
    state = HarnessMissionState(
        mission_id="mission-a",
        goal_id="goal-a",
        goal_contract={"deliverable": "MASTER_FINAL"},
        artifact_dir=tmp_path,
    )
    return state, HarnessMissionSupervisor(state)


def test_progress_is_not_stall_and_keeps_mission_runnable(tmp_path):
    state, supervisor = _supervisor(tmp_path)
    state.record_progress(
        objective_satisfied=False,
        new_information=False,
        artifact_created="script:v1",
        artifact_consumed=None,
        mission_metric_before=13.455,
        mission_metric_after=18.045,
        remaining_requirements=("reach 20 supported minutes",),
        failure_signature="editorial-gap",
        strategy="evidence-expansion",
    )
    decision = supervisor.evaluate(
        goal_satisfied=False,
        remaining_requirements=("reach 20 supported minutes",),
        eligible_capability_ids=("gta6.research",),
        budget_available=True,
        authorized_action_available=True,
        failure_signature="editorial-gap",
        strategy="evidence-expansion",
    )
    assert decision.action == "RESOLVE"
    assert state.snapshot()["mission_status"] == "RUNNABLE"


def test_same_signature_same_strategy_without_progress_forces_replan(tmp_path):
    state, supervisor = _supervisor(tmp_path)
    state.record_progress(
        objective_satisfied=False,
        new_information=False,
        artifact_created=None,
        artifact_consumed=None,
        mission_metric_before=18.045,
        mission_metric_after=18.045,
        remaining_requirements=("reach 20 supported minutes",),
        failure_signature="editorial-gap",
        strategy="same-route",
    )
    decision = supervisor.evaluate(
        goal_satisfied=False,
        remaining_requirements=("reach 20 supported minutes",),
        eligible_capability_ids=("gta6.research", "web.source.acquire"),
        budget_available=True,
        authorized_action_available=True,
        failure_signature="editorial-gap",
        strategy="same-route",
    )
    assert decision.action == "REPLAN"
    assert decision.same_route_forbidden is True
    snapshot = state.snapshot()
    assert snapshot["mission_status"] == "REPLANNING"
    assert snapshot["next_transition"] == "REPLAN_REQUIRED"


def test_terminal_requires_no_governed_continuation(tmp_path):
    state, supervisor = _supervisor(tmp_path)
    decision = supervisor.evaluate(
        goal_satisfied=False,
        remaining_requirements=("missing requirement",),
        eligible_capability_ids=(),
        budget_available=False,
        authorized_action_available=False,
    )
    assert decision.action == "FAILED_TERMINAL"
    assert state.snapshot()["mission_status"] == "FAILED_TERMINAL"



def test_repeated_identical_artifact_with_zero_delta_forces_replan(tmp_path):
    state, supervisor = _supervisor(tmp_path)
    common = dict(
        objective_satisfied=False,
        new_information=False,
        artifact_created="artifact:task-results/editorial_script-3.json",
        artifact_consumed=None,
        mission_metric_before=15.409,
        mission_metric_after=15.409,
        remaining_requirements=("reach 20 supported minutes",),
        failure_signature="editorial_script:INSUFFICIENT_EVIDENCE:15.409",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
    )
    first = state.record_progress(**common)
    assert first["measurable_progress"] is True
    assert first["artifact_created_novel"] is True

    second = state.record_progress(**common)
    assert second["measurable_progress"] is False
    assert second["artifact_created_novel"] is False

    decision = supervisor.evaluate(
        goal_satisfied=False,
        remaining_requirements=("reach 20 supported minutes",),
        eligible_capability_ids=("harness.semantic.requirement.resolve",),
        budget_available=True,
        authorized_action_available=True,
        failure_signature="editorial_script:INSUFFICIENT_EVIDENCE:15.409",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        replay_detected=bool(second.get("replayed")),
    )
    assert decision.action == "REPLAN"
    assert decision.same_route_forbidden is True



def test_rehydrate_does_not_advance_logical_state_version(tmp_path):
    state,_ = _supervisor(tmp_path)
    before=state.snapshot()
    restored=HarnessMissionState(
        mission_id="mission-a",
        goal_id="goal-a",
        goal_contract={"deliverable":"MASTER_FINAL"},
        artifact_dir=tmp_path,
    )
    after=restored.snapshot()
    assert after["state_version"] == before["state_version"]
    assert after["storage_revision"] == before["storage_revision"] + 1


def test_task_result_replay_is_idempotent_and_no_false_progress(tmp_path):
    state,_ = _supervisor(tmp_path)
    common=dict(
        objective_satisfied=False,
        new_information=True,
        artifact_created="artifact:task-results/editorial_script-4.json",
        artifact_consumed=None,
        artifact_created_digest="sha256:semantic-editorial-v4",
        artifact_consumed_digest=None,
        evidence_refs=("evidence:a",),
        completed_task_ids=("editorial_script",),
        mission_metric_before=15.409,
        mission_metric_after=24.636,
        remaining_requirements=("build product",),
        failure_signature="production:PRIMARY_SOURCE_MISSING",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        logical_task_id="editorial_script",
        task_result_identity="sha256:semantic-editorial-v4",
        effective_input_digest="sha256:input-a",
        route_identity="route-a",
        physical_attempt_id="github-actions:1:1",
    )
    first=state.record_progress(**common)
    snap=state.snapshot()
    replay=state.record_progress(
        **{**common,"physical_attempt_id":"github-actions:2:1",
           "mission_metric_before":24.636}
    )
    after=state.snapshot()
    assert first["measurable_progress"] is True
    assert replay["replayed"] is True
    assert replay["measurable_progress"] is False
    assert after["state_version"] == snap["state_version"]
    assert after["completed_nodes"] == ["editorial_script"]
    assert len(after["progress_ledger"]) == 1


def test_new_artifact_path_same_semantic_digest_is_not_new_progress(tmp_path):
    state,_ = _supervisor(tmp_path)
    first=state.record_progress(
        objective_satisfied=False,new_information=False,
        artifact_created="artifact:a.json",artifact_consumed=None,
        artifact_created_digest="sha256:same",
        mission_metric_before=10,mission_metric_after=10,
        logical_task_id="task-a",task_result_identity="result-a",
    )
    second=state.record_progress(
        objective_satisfied=False,new_information=False,
        artifact_created="artifact:b.json",artifact_consumed=None,
        artifact_created_digest="sha256:same",
        mission_metric_before=10,mission_metric_after=10,
        logical_task_id="task-a",task_result_identity="result-b",
    )
    assert first["artifact_created_novel"] is True
    assert second["artifact_created_novel"] is False
    assert second["measurable_progress"] is False


def test_duplicate_evidence_is_not_new_information(tmp_path):
    state,_ = _supervisor(tmp_path)
    state.record_progress(
        objective_satisfied=False,new_information=True,
        artifact_created=None,artifact_consumed=None,
        evidence_refs=("evidence:a",),
        mission_metric_before=1,mission_metric_after=1,
        logical_task_id="task-a",task_result_identity="r1",
    )
    second=state.record_progress(
        objective_satisfied=False,new_information=True,
        artifact_created=None,artifact_consumed=None,
        evidence_refs=("evidence:a",),
        mission_metric_before=1,mission_metric_after=1,
        logical_task_id="task-a",task_result_identity="r2",
    )
    assert second["new_information"] is False
    assert second["new_evidence_refs"] == []
    assert second["measurable_progress"] is False


def test_metric_regression_requires_typed_invalidation(tmp_path):
    state,_ = _supervisor(tmp_path)
    import pytest
    with pytest.raises(
        ValueError,
        match="MISSION_METRIC_REGRESSION_REQUIRES_TYPED_INVALIDATION",
    ):
        state.record_progress(
            objective_satisfied=False,new_information=False,
            artifact_created=None,artifact_consumed=None,
            mission_metric_before=24.636,mission_metric_after=15.409,
        )
    row=state.record_progress(
        objective_satisfied=False,new_information=False,
        artifact_created=None,artifact_consumed=None,
        mission_metric_before=24.636,mission_metric_after=15.409,
        invalidation={
            "INVALIDATION_REASON":"evidence retracted",
            "SUPERSEDED_RESULT_REF":"artifact:old",
            "CAUSAL_EVIDENCE":"artifact:retraction",
        },
    )
    assert row["invalidation"]["INVALIDATION_REASON"]=="evidence retracted"


def test_same_effective_input_route_and_replay_forces_replan(tmp_path):
    state,supervisor=_supervisor(tmp_path)
    common=dict(
        objective_satisfied=False,new_information=False,
        artifact_created="artifact:result-a",artifact_consumed=None,
        artifact_created_digest="sha256:result-a",
        mission_metric_before=24.636,mission_metric_after=24.636,
        failure_signature="production:PRIMARY_SOURCE_MISSING",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        logical_task_id="production_runtime",
        task_result_identity="failure-a",
        effective_input_digest="sha256:input-a",
        route_identity="route-a",
    )
    state.record_progress(**common)
    replay=state.record_progress(**common)
    decision=supervisor.evaluate(
        goal_satisfied=False,
        remaining_requirements=("official primary source",),
        eligible_capability_ids=("harness.semantic.requirement.resolve",),
        budget_available=True,
        authorized_action_available=True,
        failure_signature="production:PRIMARY_SOURCE_MISSING",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        effective_input_digest="sha256:input-a",
        route_identity="route-a",
        replay_detected=replay["replayed"],
    )
    assert decision.action=="REPLAN"
    assert decision.same_route_forbidden is True



def test_checkpoint_rewrite_does_not_advance_state_version(tmp_path):
    state,_=_supervisor(tmp_path)
    before=state.snapshot()
    state.persist_operational_metadata(
        checkpoint_artifact_digest="sha256:"+"a"*64,
        source_run_id=123,
    )
    after=state.snapshot()
    assert after["state_version"]==before["state_version"]
    assert after["storage_revision"]==before["storage_revision"]+1


def test_identical_supervisor_decision_does_not_advance_state_version(tmp_path):
    state,supervisor=_supervisor(tmp_path)
    before=int(state.snapshot()["state_version"])
    decision=supervisor.evaluate(
        goal_satisfied=False,
        remaining_requirements=("PRODUCT_ASSEMBLY_REQUIRED",),
        eligible_capability_ids=("harness.semantic.requirement.resolve",),
        budget_available=True,
        authorized_action_available=True,
        failure_signature="production:PRODUCT_ASSEMBLY_REQUIRED",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        effective_input_digest="sha256:"+"a"*64,
        route_identity="route:sha256:"+"b"*64,
    )
    state.persist_supervisor_decision(
        decision,
        state_version_before_evaluate=before,
        extra={
            "failure_signature":"production:PRODUCT_ASSEMBLY_REQUIRED",
            "strategy":"MINIMAL_AFFECTED_SUBGRAPH",
        },
    )
    once=state.snapshot()
    version_before=int(once["state_version"])
    same=supervisor.evaluate(
        goal_satisfied=False,
        remaining_requirements=("PRODUCT_ASSEMBLY_REQUIRED",),
        eligible_capability_ids=("harness.semantic.requirement.resolve",),
        budget_available=True,
        authorized_action_available=True,
        failure_signature="production:PRODUCT_ASSEMBLY_REQUIRED",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        effective_input_digest="sha256:"+"a"*64,
        route_identity="route:sha256:"+"b"*64,
    )
    state.persist_supervisor_decision(
        same,
        state_version_before_evaluate=version_before,
        extra={
            "failure_signature":"production:PRODUCT_ASSEMBLY_REQUIRED",
            "strategy":"MINIMAL_AFFECTED_SUBGRAPH",
        },
    )
    after=state.snapshot()
    assert after["state_version"]==once["state_version"]
    assert after["storage_revision"]>once["storage_revision"]


def test_real_logical_change_advances_state_version_once(tmp_path):
    state,supervisor=_supervisor(tmp_path)
    before=int(state.snapshot()["state_version"])
    decision=supervisor.evaluate(
        goal_satisfied=False,
        remaining_requirements=("PRODUCT_ASSEMBLY_REQUIRED",),
        eligible_capability_ids=("harness.semantic.requirement.resolve",),
        budget_available=True,
        authorized_action_available=True,
        failure_signature="production:PRODUCT_ASSEMBLY_REQUIRED",
        strategy="MINIMAL_AFFECTED_SUBGRAPH",
        effective_input_digest="sha256:"+"a"*64,
        route_identity="route:sha256:"+"b"*64,
    )
    state.persist_supervisor_decision(
        decision,
        state_version_before_evaluate=before,
        extra={
            "failure_signature":"production:PRODUCT_ASSEMBLY_REQUIRED",
            "strategy":"MINIMAL_AFFECTED_SUBGRAPH",
        },
    )
    assert state.snapshot()["state_version"]==before+1
