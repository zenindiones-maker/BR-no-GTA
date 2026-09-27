from datetime import datetime, timedelta, timezone
import inspect

from app.services.provider_availability_reconciliation_service import (
    ProviderAvailabilityBackoffPolicy,
    ProviderAvailabilityReconciler,
    build_provider_availability_wait,
    classify_unschedulable_reason,
    deterministic_backoff_seconds,
)


NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _failure_evidence():
    snapshot = {
        "schema": "ProviderEligibilitySnapshot/v1",
        "snapshot_ref": "objects/provider-eligibility/sha256/elig-a.json",
        "content_sha256": "elig-a",
        "HEALTH_ELIGIBLE_PROVIDER_COUNT": 1,
        "effective_provider_count": 0,
        "effective_model_pair_count": 0,
        "rejected_candidates": [{
            "candidate_id": "provider-a:model-a",
            "provider_id": "provider-a",
            "model_id": "model-a",
            "status": "REJECTED",
            "reasons": ["provider_model_pair_exhausted"],
        }],
    }
    return {
        "routing_policy_error": {
            "evidence": {
                "failure_class": "PROVIDER_POOL_EXHAUSTED",
                "failure_stage": "provider_selection",
                "provider_eligibility_snapshot": snapshot,
                "provider_eligibility_snapshot_ref": snapshot["snapshot_ref"],
                "provider_eligibility_snapshot_sha256": "elig-a",
                "reconciliation_request": {
                    "schema": "ProviderRoutingReconciliationRequest/v1",
                    "intent": "semantic task",
                    "authorized_action": "DEVELOPMENT",
                    "domain": "ai",
                    "required_capability_id": "ai.reasoning.text",
                    "provider_required": True,
                    "provider_domain": "ai",
                    "allowed_providers": ["provider-a", "provider-b"],
                    "unavailable_provider_ids": ["provider-a"],
                    "exhausted_provider_model_pairs": [
                        ["provider-a", "model-a"],
                    ],
                    "zero_cost_operation": True,
                    "mission_id": "mission-a",
                    "task_id": "task-02",
                    "agent_instance_id": "agent-a",
                    "recovery_phase": "PROVIDER_LEVEL_REPLAN",
                    "provider_level_replan_authorized": True,
                    "from_provider": "provider-a",
                    "health_eligible_provider_ids": ["provider-a"],
                },
            },
        },
        "provider_health_snapshot": {
            "schema": "ProviderHealthSnapshot/v1",
            "snapshot_ref": "objects/provider-health/sha256/content-a.json",
            "snapshot_sha256": "content-a",
            "material_state_sha256": "health-a",
            "observed_at": NOW.isoformat(),
            "providers": [],
        },
    }


def _wait(tmp_path):
    return build_provider_availability_wait(
        artifact_dir=tmp_path,
        mission_id="mission-a",
        plan_id="plan-a",
        plan_revision=7,
        task_id="task-02",
        failure_signature="f" * 64,
        failure_evidence=_failure_evidence(),
        internal_recovery={
            "PREVIOUS_SELECTED_PROVIDER": "provider-a",
            "TEMPORARILY_EJECTED_PROVIDER_IDS": ["provider-a"],
            "EXHAUSTED_PROVIDER_MODEL_PAIRS": [{
                "provider_id": "provider-a",
                "model_id": "model-a",
            }],
            "PROVIDER_CIRCUIT_STATES": {"provider-a": "OPEN"},
        },
        now=NOW,
    )


def _health(hash_value="health-a", providers=None):
    return {
        "schema": "ProviderHealthSnapshot/v1",
        "snapshot_ref": f"objects/provider-health/sha256/{hash_value}.json",
        "snapshot_sha256": f"content-{hash_value}",
        "material_state_sha256": hash_value,
        "observed_at": (NOW + timedelta(minutes=1)).isoformat(),
        "providers": providers or [],
        "eligible_zero_cost_provider_ids": [],
        "HEALTH_ELIGIBLE_PROVIDER_COUNT": 0,
    }


def _reconcile(tmp_path, *, health_hash="health-a", providers=None):
    return ProviderAvailabilityReconciler().reconcile(
        wait=_wait(tmp_path),
        artifact_dir=tmp_path,
        now=NOW + timedelta(minutes=2),
        health_snapshot=_health(health_hash, providers=providers),
    )


def test_provider_pool_exhausted_enters_wait_state(tmp_path):
    wait = _wait(tmp_path)
    assert wait["status"] == "WAITING_FOR_PROVIDER_AVAILABILITY"
    assert wait["failure_class"] == "PROVIDER_POOL_EXHAUSTED"
    assert wait["MISSION_TERMINAL"] is False


def test_provider_pool_exhausted_not_generic_replan(tmp_path):
    assert _wait(tmp_path)["status"] != "REPLAN_REQUIRED"


def test_provider_pool_exhausted_not_human_gate(tmp_path):
    assert _wait(tmp_path)["HUMAN_INTERVENTION_REQUIRED"] is False


def test_wait_state_persists_mission_id(tmp_path):
    wait = _wait(tmp_path)
    assert wait["mission_id"] == "mission-a"
    assert wait["plan_revision"] == 7


def test_wait_state_releases_execution_lease(tmp_path):
    assert "execution_lease" not in _wait(tmp_path)


def test_wait_state_consumes_zero_provider_calls(tmp_path):
    assert _wait(tmp_path)["PROVIDER_CALLS_WHILE_WAITING"] == 0


def test_wait_state_consumes_zero_agent_turns(tmp_path):
    assert _wait(tmp_path)["AGENT_TURNS_WHILE_WAITING"] == 0


def test_wait_state_consumes_zero_semantic_planner_calls(tmp_path):
    assert _wait(tmp_path)["SEMANTIC_PLANNER_CALLS_WHILE_WAITING"] == 0


def test_unchanged_health_hash_does_not_requeue(tmp_path):
    result = _reconcile(tmp_path)
    assert result["decision"] == "STILL_WAITING"
    assert result["RECONCILIATION_NO_STATE_CHANGE"] == "PASS"


def test_unchanged_eligibility_hash_does_not_requeue(tmp_path):
    result = _reconcile(tmp_path)
    assert result["new_effective_count"] == 0
    assert result["decision"] == "STILL_WAITING"


def test_health_change_with_zero_pool_stays_waiting(tmp_path):
    result = _reconcile(tmp_path, health_hash="health-b")
    assert result["state_changed"] is True
    assert result["new_effective_count"] == 0
    assert result["decision"] == "STILL_WAITING"


def test_effective_pool_zero_to_nonzero_requires_real_route(tmp_path):
    result = _reconcile(
        tmp_path,
        health_hash="health-b",
        providers=[{
            "provider_id": "provider-a",
            "state": "AVAILABLE",
            "zero_cost_eligible": True,
            "models": [{
                "model_id": "model-a",
                "availability": "AVAILABLE",
                "last_verified_at": (
                    NOW + timedelta(minutes=1)
                ).isoformat(),
                "source": "CURRENT_RUN_RUNTIME_PROOF",
            }],
        }],
    )
    assert result["state_changed"] is True
    assert result["decision"] == "STILL_WAITING"


def test_requeue_preserves_plan_revision(tmp_path):
    assert _wait(tmp_path)["plan_revision"] == 7


def test_requeue_preserves_completed_results_contract(tmp_path):
    assert _wait(tmp_path)["MISSION_TERMINAL"] is False


def test_no_exhausted_pair_reuse_in_same_recovery_epoch(tmp_path):
    assert ["provider-a", "model-a"] in (
        _wait(tmp_path)["exhausted_provider_model_pairs"]
    )


def test_new_recovery_epoch_requires_typed_evidence(tmp_path):
    result = _reconcile(tmp_path, health_hash="health-b")
    assert result["provider_recovery_epoch"]["epoch"] == 0


def test_circuit_open_provider_not_effective(tmp_path):
    wait = _wait(tmp_path)
    assert wait["provider_circuit_states"]["provider-a"] == "OPEN"
    assert wait["effective_provider_count"] == 0


def test_half_open_single_probe_only(tmp_path):
    assert _reconcile(tmp_path)["HALF_OPEN_SINGLE_PROBE_ONLY"] == (
        "NOT_APPLICABLE"
    )


def test_half_open_success_can_open_new_epoch(tmp_path):
    result = _reconcile(
        tmp_path,
        health_hash="health-b",
        providers=[{
            "provider_id": "provider-a",
            "state": "AVAILABLE",
            "zero_cost_eligible": True,
            "models": [{
                "model_id": "model-a",
                "availability": "AVAILABLE",
                "last_verified_at": (
                    NOW + timedelta(minutes=1)
                ).isoformat(),
                "source": "CURRENT_RUN_RUNTIME_PROOF",
            }],
        }],
    )
    assert result["provider_recovery_epoch"]["epoch"] == 1
    assert result["recovered_provider_ids"] == ["provider-a"]
    assert result["HALF_OPEN_SINGLE_PROBE_ONLY"] == "PASS"
    assert result["circuit_transitions"]["provider-a"] == {
        "from_state": "OPEN",
        "probe_state": "HALF_OPEN",
        "to_state": "CLOSED",
        "probe_kind": "BOUNDED_EXTERNAL_HEALTH_PROOF",
        "semantic_task_used_as_probe": False,
    }


def test_half_open_failure_returns_to_wait(tmp_path):
    assert _reconcile(
        tmp_path,
        health_hash="health-b",
    )["decision"] == "STILL_WAITING"


def test_structural_unschedulable_not_retried_forever():
    reason = classify_unschedulable_reason(
        rejected_candidates=[],
        mission_local_exclusions=[],
        exhausted_provider_model_pairs=[],
        effective_provider_count=0,
    )
    assert reason.reason_class == "NO_COMPATIBLE_PROVIDER_REGISTERED"
    assert reason.wait_allowed is False
    assert reason.policy_replan is True


def test_auth_required_escalates_only_when_no_compliant_route():
    reason = classify_unschedulable_reason(
        rejected_candidates=[{"reasons": ["AUTH_REQUIRED"]}],
        mission_local_exclusions=[],
        exhausted_provider_model_pairs=[],
        effective_provider_count=0,
    )
    assert reason.human_gate is True


def test_duplicate_reconciliation_is_idempotent(tmp_path):
    wait = _wait(tmp_path)
    reconciler = ProviderAvailabilityReconciler()
    first = reconciler.reconcile(
        wait=wait,
        artifact_dir=tmp_path,
        now=NOW + timedelta(seconds=5),
        health_snapshot=_health("health-a"),
    )
    second = reconciler.reconcile(
        wait=wait,
        artifact_dir=tmp_path,
        now=NOW + timedelta(hours=3),
        health_snapshot=_health("health-z"),
    )
    assert first == second


def test_reconciliation_backoff_bounded():
    policy = ProviderAvailabilityBackoffPolicy(
        initial_delay_seconds=30,
        multiplier=2,
        max_delay_seconds=120,
        jitter_fraction=0.15,
    )
    first = [
        deterministic_backoff_seconds(
            mission_id="m",
            task_id="t",
            failure_signature="f",
            reconciliation_attempt=index,
            policy=policy,
        )
        for index in range(1, 12)
    ]
    second = [
        deterministic_backoff_seconds(
            mission_id="m",
            task_id="t",
            failure_signature="f",
            reconciliation_attempt=index,
            policy=policy,
        )
        for index in range(1, 12)
    ]
    assert first == second
    assert all(0 <= value <= 120 for value in first)


def test_max_wait_reclassifies_without_terminal_failure(tmp_path):
    wait = _wait(tmp_path)
    result = ProviderAvailabilityReconciler(
        policy=ProviderAvailabilityBackoffPolicy(
            max_reconciliation_attempts=1,
            max_wait_window_seconds=1,
        )
    ).reconcile(
        wait=wait,
        artifact_dir=tmp_path,
        now=NOW + timedelta(hours=1),
        health_snapshot=_health("health-a"),
    )
    assert result["bounded_wait_exhausted"] is True
    assert result["decision"] == "STILL_WAITING"
    assert result["human_intervention_required"] is False
    assert result["wake_condition"] == (
        "BOUNDED_WAIT_EXHAUSTED_TEMPORARY_DEFER"
    )


def test_no_long_sleep_in_github_runner():
    import app.services.provider_availability_reconciliation_service as service
    assert "sleep(" not in inspect.getsource(service)


def test_no_second_control_plane():
    import app.services.provider_availability_reconciliation_service as service
    source = inspect.getsource(service)
    assert "DEEPSEEK_HARNESS" in source
    assert "execute_delegated_capability" not in source


def test_real_path_36285454407_enters_wait(tmp_path):
    wait = _wait(tmp_path)
    assert wait["effective_provider_count"] == 0
    assert wait["failure_class"] == "PROVIDER_POOL_EXHAUSTED"
    assert wait["status"] == "WAITING_FOR_PROVIDER_AVAILABILITY"
    assert wait["PROVIDER_CALLS_WHILE_WAITING"] == 0
    assert wait["HUMAN_INTERVENTION_REQUIRED"] is False
    assert wait["MISSION_TERMINAL"] is False
