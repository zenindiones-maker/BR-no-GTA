from types import SimpleNamespace

from app.services.harness_internal_recovery_service import (
    CONTRACT_INPUT_GAP,
    PROVIDER_TRANSIENT,
    HarnessInternalRecoveryState,
    classify_internal_failure,
)
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
