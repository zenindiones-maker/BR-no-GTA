from __future__ import annotations

from app.services.agent_session_service import AgentSessionRuntime
from app.services.harness_mission_execution_router import (
    resolve_harness_execution_need,
)
from app.services.hermes_multiagent.capability_broker import (
    DelegatedCapabilityFailure,
)
from scripts.dynamic_system_improvement_mission import (
    _release_execution_lease_for_provider_wait,
)


def _session(tmp_path):
    return AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-a",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=4,
        max_provider_calls=8,
        max_context_chars=16000,
        max_wall_clock_seconds=300,
    )


def test_broker_preserves_provider_pool_exhausted_typed_need():
    failure = DelegatedCapabilityFailure(
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        failure_mode="RoutingPolicyError",
        retry_attempt=0,
        retry_allowed=False,
        requires_harness_replan=True,
        failure_evidence={
            "routing_policy_error": {
                "evidence": {
                    "failure_stage": "provider_selection",
                    "failure_class": "PROVIDER_POOL_EXHAUSTED",
                    "EFFECTIVE_ROUTING_PROVIDER_COUNT": 0,
                }
            }
        },
    )
    assert failure.need["failure_class"] == "PROVIDER_POOL_EXHAUSTED"
    assert failure.need["status"] == "WAITING_FOR_PROVIDER_AVAILABILITY"
    assert failure.need["retryability"] == "NOT_EXECUTABLE_NOW"
    assert failure.need["replan_required"] is False


def test_execution_need_routes_provider_pool_exhausted_to_wait(tmp_path):
    result = resolve_harness_execution_need(
        mission_plan={
            "mission_id": "mission-a",
            "plan_id": "plan-a",
            "plan_revision": 7,
        },
        need={
            "schema": "HarnessExecutionNeed/v1",
            "status": "WAITING_FOR_PROVIDER_AVAILABILITY",
            "failure_class": "PROVIDER_POOL_EXHAUSTED",
            "semantic_requirement": (
                "provider availability reconciliation without semantic replanning"
            ),
            "retryability": "NOT_EXECUTABLE_NOW",
            "replan_required": False,
            "causal_task_id": "task-02",
            "producer_selected_resolver": False,
        },
        planning_context={},
        artifact_dir=tmp_path,
    )
    transition = result["mission_state_update"]
    assert transition["decision"] == "WAIT_FOR_PROVIDER_AVAILABILITY"
    assert transition["mission_status"] == "WAITING_FOR_PROVIDER_AVAILABILITY"
    assert transition["mission_terminal"] is False
    assert transition["human_intervention_required"] is False
    assert transition["preserve_completed_results"] is True
    assert result["resolution"] is None


def test_recovery_epoch_only_reenables_provider_with_typed_evidence(tmp_path):
    session = _session(tmp_path)
    session.fail(
        failure_class="PROVIDER_POOL_EXHAUSTED",
        evidence={
            "provider_attempts": [
                {
                    "attempt_id": "a1",
                    "provider_id": "provider-a",
                    "model_id": "model-a",
                    "routing_id": "route-a",
                    "status": "FAILED",
                    "failure_class": "TRANSIENT_PROVIDER_TIMEOUT",
                    "recovery_epoch_id": "initial",
                },
                {
                    "attempt_id": "b1",
                    "provider_id": "provider-b",
                    "model_id": "model-b",
                    "routing_id": "route-b",
                    "status": "FAILED",
                    "failure_class": "TRANSIENT_PROVIDER_HTTP_5XX",
                    "recovery_epoch_id": "initial",
                },
            ],
            "FAILURE_DOMAIN_CLASSIFICATION": {
                "schema": "FailureDomainClassification/v1",
                "provider_id": "provider-a",
                "scope": "PROVIDER_LOCAL",
                "provider_ejected": True,
                "provider_circuit": {
                    "from_state": "CLOSED",
                    "to_state": "OPEN",
                },
            },
        },
        turn_consumed=False,
    )
    before = session.snapshot()
    session.apply_provider_recovery_epoch(
        {
            "schema": "ProviderRecoveryEpoch/v1",
            "epoch_id": "epoch-1",
            "epoch": 1,
            "opened_at": "2026-09-27T12:10:00+00:00",
            "reset_condition": "NEW_MODEL_LIVE_PROOF",
            "reset_evidence": [
                "github:run:health-proof:provider-a",
            ],
            "recovered_provider_ids": ["provider-a"],
        },
        requeue_ready=True,
    )
    recovery = session.provider_recovery_state()
    exhausted = {
        (row["provider_id"], row["model_id"])
        for row in recovery["EXHAUSTED_PROVIDER_MODEL_PAIRS"]
    }
    assert ("provider-a", "model-a") not in exhausted
    assert ("provider-b", "model-b") in exhausted
    assert recovery["RECOVERY_STRATEGY"] == "PROVIDER_AVAILABILITY_REQUEUE"
    assert recovery["PROVIDER_CALL_COUNT"] == 2
    assert recovery["HISTORICAL_PROVIDER_ATTEMPT_COUNT"] == 2
    assert session.snapshot()["TURN_INDEX"] == before["TURN_INDEX"]


def test_new_epoch_without_typed_schema_is_rejected(tmp_path):
    session = _session(tmp_path)
    try:
        session.apply_provider_recovery_epoch(
            {
                "epoch_id": "epoch-untyped",
                "recovered_provider_ids": ["provider-a"],
            },
            requeue_ready=True,
        )
    except ValueError as exc:
        assert "ProviderRecoveryEpoch/v1" in str(exc)
    else:
        raise AssertionError("untyped recovery epoch was accepted")


def test_wait_state_releases_execution_lease():
    class Board:
        def __init__(self):
            self.status = "claimed"
            self.block_calls = []

        def block(self, task_id, *, reason, run_id, kind):
            self.block_calls.append(
                (task_id, reason, run_id, kind)
            )
            self.status = "blocked"
            return True

        def get_task(self, task_id):
            return {"id": task_id, "status": self.status}

    board = Board()
    released = _release_execution_lease_for_provider_wait(
        board,
        {"task-02": "board-task-02"},
        "task-02",
        41,
    )
    assert released is True
    assert board.status == "blocked"
    assert board.block_calls == [(
        "board-task-02",
        "HARNESS_NONTERMINAL_PROVIDER_AVAILABILITY_WAIT",
        41,
        "needs_input",
    )]
