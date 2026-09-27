from app.services.provider_failure_domain_service import (
    classify_failure_domain,
    provider_admission_state,
    transition_provider_circuit,
)


def _failed(
    model,
    attempt,
    failure_class,
    *,
    code=None,
    stage=None,
    status_code=500,
):
    return {
        "attempt_id": attempt,
        "agent_turn": 1,
        "phase": "INITIAL",
        "routing_id": "route-" + attempt,
        "provider_id": "provider-a",
        "model_id": model,
        "status": "FAILED",
        "failure_class": failure_class,
        "failure_evidence": {
            "code": code,
            "failure_stage": stage,
            "status_code": status_code,
            "retryable": True,
        },
    }


def test_correlated_multi_model_failure_classifies_provider_local():
    attempts = [
        _failed(
            "model-a", "a1", "TRANSIENT_PROVIDER_HTTP_5XX",
            code="upstream_error", stage="transport_response",
        ),
        _failed(
            "model-a", "a2", "TRANSIENT_PROVIDER_HTTP_5XX",
            code="upstream_error", stage="transport_response",
        ),
        _failed(
            "model-b", "b1", "TRANSIENT_PROVIDER_TIMEOUT",
            code="timeout", stage="transport_request", status_code=None,
        ),
    ]
    result = classify_failure_domain(
        mission_id="mission-a",
        task_id="task-a",
        agent_instance_id="agent-a",
        provider_id="provider-a",
        model_id="model-b",
        attempts=attempts,
        eligible_models_at_cycle_start=4,
    )
    assert result["scope"] == "PROVIDER_LOCAL"
    assert result["provider_ejected"] is True
    assert result["provider_circuit"]["to_state"] == "OPEN"
    assert result["provider_recovery_reserve"]["reserve_preserved"] is True
    assert result["provider_recovery_reserve"][
        "provider_ejected_before_full_exhaustion"
    ] is True


def test_model_local_failure_does_not_eject_provider():
    result = classify_failure_domain(
        mission_id="mission-a",
        task_id="task-a",
        agent_instance_id="agent-a",
        provider_id="provider-a",
        model_id="model-a",
        attempts=[_failed(
            "model-a", "a1", "MODEL_UNAVAILABLE",
            code="model_unavailable", stage="model_selection",
            status_code=None,
        )],
        eligible_models_at_cycle_start=4,
    )
    assert result["scope"] == "MODEL_LOCAL"
    assert result["provider_ejected"] is False
    assert result["decision"] == "ALLOW_ALTERNATE_MODEL"


def test_provider_circuit_open_blocks_model_calls():
    decision = provider_admission_state(
        provider_id="provider-a",
        circuit_state="OPEN",
        effective_eligible=True,
        half_open_probe_claimed=False,
        retry_budget_remaining=1,
    )
    assert decision["decision"] == "ROUTE_ELSEWHERE"


def test_half_open_allows_single_probe_only():
    first = provider_admission_state(
        provider_id="provider-a",
        circuit_state="HALF_OPEN",
        effective_eligible=True,
        half_open_probe_claimed=False,
        retry_budget_remaining=1,
    )
    second = provider_admission_state(
        provider_id="provider-a",
        circuit_state="HALF_OPEN",
        effective_eligible=True,
        half_open_probe_claimed=True,
        retry_budget_remaining=1,
    )
    assert first["decision"] == "ADMIT"
    assert first["single_half_open_probe"] is True
    assert second["decision"] == "DEFER"


def test_half_open_success_closes_and_failure_reopens():
    assert transition_provider_circuit(
        "OPEN", "COOLDOWN_ELAPSED"
    )["to_state"] == "HALF_OPEN"
    assert transition_provider_circuit(
        "HALF_OPEN", "PROBE_SUCCESS"
    )["to_state"] == "CLOSED"
    assert transition_provider_circuit(
        "HALF_OPEN", "PROBE_FAILURE"
    )["to_state"] == "OPEN"
