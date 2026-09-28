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
    )
    assert decision.action == "REPLAN"
    assert decision.same_route_forbidden is True
