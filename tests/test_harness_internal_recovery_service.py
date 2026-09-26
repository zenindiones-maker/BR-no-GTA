from types import SimpleNamespace

from app.services.harness_internal_recovery_service import (
    CONTRACT_INPUT_GAP,
    MODEL_SET_EXHAUSTED,
    PROVIDER_POOL_EXHAUSTED,
    PROVIDER_ROUTE_UNAVAILABLE,
    PROVIDER_TRANSIENT,
    REGISTRY_SELECTION_GAP,
    HarnessInternalRecoveryState,
    classify_internal_failure,
)
from app.services.harness_routing_policy_service import RoutingPolicyError
from app.services.task_input_contract_service import (
    TaskInputContractViolation,
    resolve_task_input_contract,
)


def _task():
    return SimpleNamespace(
        task_id="task-02",
        task_class="incident-diagnosis",
        capability_id="addy:debugging-and-error-recovery",
        capability_version="1",
    )


def test_input_gap_classifies_and_recovers_once(tmp_path):
    validation = resolve_task_input_contract(
        functional_role="REVIEW",
        parent_handoffs=[],
    )
    failure = TaskInputContractViolation(validation)
    classification = classify_internal_failure(
        failure,
        task=_task(),
        context={"dependency_context_sha256": "abc"},
    )
    assert classification.failure_class == CONTRACT_INPUT_GAP
    assert classification.recoverable is True

    state = HarnessInternalRecoveryState(
        mission_id="mission-a",
        goal_id="goal-a",
        artifact_dir=tmp_path,
    )
    state.task_started("task-02")
    observed = state.observe_failure(
        task=_task(),
        exc=failure,
        context={"dependency_context_sha256": "abc"},
    )
    decision = state.select_recovery(observed)
    assert decision.strategy == "RECOMPUTE_TYPED_INPUT_SCOPE"
    state.recovery_started(
        classification=observed,
        decision=decision,
    )
    state.recovery_validated(
        task_id="task-02",
        validation="INPUT_CONTRACT_VALID=PASS",
    )
    state.task_resumed("task-02")
    state.task_completed("task-02")
    snapshot = state.snapshot()
    assert snapshot["LAST_SUCCESSFUL_TASK"] == "task-02"
    events = [item["event"] for item in snapshot["events"]]
    assert "FAILURE_CLASSIFIED" in events
    assert "RECOVERY_STARTED" in events
    assert "RECOVERY_VALIDATED" in events
    assert "TASK_RESUMED" in events


def test_provider_transient_escalates_without_repeating_strategy(tmp_path):
    failure = RuntimeError("NVIDIA NIM upstream service failed")
    classification = classify_internal_failure(
        failure,
        task=_task(),
        context={"dependency_context_sha256": "provider-lineage"},
    )
    assert classification.failure_class == PROVIDER_TRANSIENT
    state = HarnessInternalRecoveryState(
        mission_id="mission-b",
        goal_id="goal-b",
        artifact_dir=tmp_path,
    )
    observed = state.observe_failure(
        task=_task(),
        exc=failure,
        context={"dependency_context_sha256": "provider-lineage"},
    )
    first = state.select_recovery(observed)
    assert first.strategy == "RETRY_SAME_TASK"
    state.recovery_started(
        classification=observed,
        decision=first,
    )
    second = state.select_recovery(observed)
    assert second.strategy == "LOCALIZED_PROVIDER_REPLAN"
    state.recovery_started(
        classification=observed,
        decision=second,
    )
    third = state.select_recovery(observed)
    assert third.recoverable is False
    assert third.exhausted is True
    snapshot = state.snapshot()
    assert snapshot["MISSION_STATUS"] == "RECOVERING_INTERNAL"
    assert snapshot["RECOVERY_STATE"] == "LOCAL_RECOVERY_EXHAUSTED"
    assert snapshot["NEXT_TRANSITION"] == "REPLAN_REQUIRED"
    assert snapshot["MISSION_STATUS"] != "FAILED_TERMINAL"
    events = [item["event"] for item in snapshot["events"]]
    assert "LOCAL_RECOVERY_EXHAUSTED" in events


def test_capability_timeout_wording_is_provider_transient():
    failure = RuntimeError(
        "CapabilityReturnedFailure: capability returned non-executed "
        "evidence: addy:constraint-driven-development status=FAILED "
        "reason=NVIDIA NIM request timed out"
    )
    classification = classify_internal_failure(
        failure,
        task=_task(),
        context={"dependency_context_sha256": "timeout-lineage"},
    )
    assert classification.failure_class == PROVIDER_TRANSIENT
    assert classification.recoverable is True
    assert classification.human_intervention_required is False



def test_full_timeout_can_skip_same_task_retry_strategy(tmp_path):
    failure = RuntimeError("NVIDIA NIM request timed out")
    classification = classify_internal_failure(
        failure,
        task=_task(),
        context={"dependency_context_sha256": "timeout-lineage"},
    )
    state = HarnessInternalRecoveryState(
        mission_id="mission-c",
        goal_id="goal-c",
        artifact_dir=tmp_path,
    )
    observed = state.observe_failure(
        task=_task(),
        exc=failure,
        context={"dependency_context_sha256": "timeout-lineage"},
    )
    decision = state.select_recovery(
        observed,
        disallowed_strategies=("RETRY_SAME_TASK",),
    )
    assert decision.strategy == "LOCALIZED_PROVIDER_REPLAN"


def test_routing_policy_provider_stage_not_registry_gap():
    failure = RoutingPolicyError(
        "Primary provider is unavailable and fallback is not permitted",
        evidence={
            "failure_stage": "provider_selection",
            "failure_class": "PROVIDER_ROUTE_UNAVAILABLE",
            "eligible_provider_count": 1,
        },
    )
    result = classify_internal_failure(
        failure, task=_task(),
        context={"dependency_context_sha256": "provider-route"},
    )
    assert result.failure_class == PROVIDER_ROUTE_UNAVAILABLE
    assert result.failure_class != REGISTRY_SELECTION_GAP


def test_registry_selection_gap_reserved_for_capability_selection():
    failure = RoutingPolicyError(
        "No executable capability satisfies Harness routing policy",
        evidence={
            "failure_stage": "capability_selection",
            "failure_class": "REGISTRY_SELECTION_GAP",
        },
    )
    result = classify_internal_failure(
        failure, task=_task(),
        context={"dependency_context_sha256": "capability-route"},
    )
    assert result.failure_class == REGISTRY_SELECTION_GAP


def test_provider_pool_exhausted_is_internal_not_human_gate(tmp_path):
    failure = RoutingPolicyError(
        "No eligible zero-cost semantic provider is available",
        evidence={
            "failure_stage": "provider_selection",
            "failure_class": "PROVIDER_POOL_EXHAUSTED",
            "eligible_provider_count": 0,
            "zero_cost_operation": True,
        },
    )
    result = classify_internal_failure(
        failure, task=_task(),
        context={"dependency_context_sha256": "provider-health"},
    )
    assert result.failure_class == PROVIDER_POOL_EXHAUSTED
    assert result.recoverable is True
    assert result.human_intervention_required is False
    state = HarnessInternalRecoveryState(
        mission_id="mission-provider-pool",
        goal_id="goal-provider-pool",
        artifact_dir=tmp_path,
    )
    observed = state.observe_failure(
        task=_task(), exc=failure,
        context={"dependency_context_sha256": "provider-health"},
    )
    assert state.select_recovery(observed).strategy == "RECONCILE_PROVIDER_HEALTH"


def test_model_set_exhausted_selects_provider_level_replan(tmp_path):
    failure = RoutingPolicyError(
        "No effective provider/model candidates remain",
        evidence={
            "failure_stage": "provider_selection",
            "failure_class": "MODEL_SET_EXHAUSTED",
            "recovery_phase": "SAME_PROVIDER_MODEL_REPLAN",
            "EFFECTIVE_ROUTING_PROVIDER_COUNT": 0,
        },
    )
    classification = classify_internal_failure(
        failure,
        task=_task(),
        context={"dependency_context_sha256": "model-set"},
    )
    assert classification.failure_class == MODEL_SET_EXHAUSTED
    state = HarnessInternalRecoveryState(
        mission_id="mission-model-set",
        goal_id="goal-model-set",
        artifact_dir=tmp_path,
    )
    observed = state.observe_failure(
        task=_task(),
        exc=failure,
        context={"dependency_context_sha256": "model-set"},
    )
    decision = state.select_recovery(observed)
    assert decision.strategy == "PROVIDER_LEVEL_REPLAN"
    assert decision.human_intervention_required is False
