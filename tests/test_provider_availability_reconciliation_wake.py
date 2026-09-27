from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.provider_availability_reconciliation_service import (
    ProviderAvailabilityReconciler,
)


NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _nvidia_models() -> list[str]:
    return sorted({
        str(record.model_id)
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.capability_type == "PROVIDER"
        and record.provider_id == "nvidia_nim"
        and record.model_id
    })


def test_real_path_wake_requeues_same_mission(monkeypatch, tmp_path):
    run_id = "provider-wake-fixture"
    models = _nvidia_models()
    assert models
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key")
    monkeypatch.setenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        json.dumps({
            "nvidia_nim": {
                model_id: {
                    "availability": "AVAILABLE",
                    "latency_ms": 1000,
                    "confidence": 0.95,
                    "sample_size": 1,
                    "rate_limit_state": "CLEAR",
                    "circuit_breaker_state": "CLOSED",
                    "github_run_id": run_id,
                    "evidence_refs": [
                        f"github:run:{run_id}:nvidia-model:{model_id}"
                    ],
                    "last_verified_at": (
                        NOW + timedelta(minutes=1)
                    ).isoformat(),
                    "live_status": "PASS",
                    "quota_state": "CLEAR",
                }
                for model_id in models
            }
        }),
    )
    wait = {
        "schema": "ProviderAvailabilityWait/v1",
        "authority": "DEEPSEEK_HARNESS",
        "mission_id": "mission-real-path",
        "plan_id": "plan-real-path",
        "plan_revision": 4,
        "task_id": "task-02",
        "agent_instance_id": "agent-real-path",
        "failure_signature": "f" * 64,
        "failure_class": "PROVIDER_POOL_EXHAUSTED",
        "effective_provider_count": 0,
        "effective_model_pair_count": 0,
        "mission_local_exclusions": ["nvidia_nim"],
        "exhausted_provider_model_pairs": [
            ["nvidia_nim", model_id] for model_id in models
        ],
        "provider_circuit_states": {"nvidia_nim": "OPEN"},
        "provider_recovery_epoch": {
            "schema": "ProviderRecoveryEpoch/v1",
            "epoch_id": "provider-recovery-epoch-0",
            "epoch": 0,
            "opened_at": NOW.isoformat(),
            "reset_evidence": [],
            "recovered_provider_ids": [],
        },
        "routing_request": {
            "schema": "ProviderRoutingReconciliationRequest/v1",
            "intent": "real-path semantic diagnosis",
            "authorized_action": "DEVELOPMENT",
            "domain": "ai",
            "task_class": "addy-semantic:debugging-and-error-recovery",
            "required_capability_id": "ai.reasoning.text",
            "provider_required": True,
            "provider_domain": "ai",
            "preferred_providers": [],
            "allowed_providers": ["nvidia_nim"],
            "preferred_models": [],
            "unavailable_provider_ids": ["nvidia_nim"],
            "unavailable_model_ids": [],
            "exhausted_provider_model_pairs": [
                ["nvidia_nim", model_id] for model_id in models
            ],
            "fallback_allowed": False,
            "zero_cost_operation": True,
            "task_id": "task-02",
            "mission_id": "mission-real-path",
            "agent_instance_id": "agent-real-path",
            "recovery_phase": "PROVIDER_LEVEL_REPLAN",
            "provider_level_replan_authorized": True,
            "from_provider": "nvidia_nim",
            "required_model_capabilities": [
                "reasoning",
                "semantic_planning",
                "structured_output",
            ],
            "structured_output_required": True,
            "health_eligible_provider_ids": ["nvidia_nim"],
        },
        "wait_started_at": NOW.isoformat(),
        "reconciliation_attempt": 0,
        "max_reconciliation_attempts": 8,
        "not_before": (NOW + timedelta(seconds=30)).isoformat(),
        "last_observed_health_hash": "health-old",
        "last_observed_eligibility_hash": "eligibility-old",
        "provider_health_snapshot_ref": "objects/provider-health/old.json",
        "provider_eligibility_snapshot_ref": (
            "objects/provider-eligibility/old.json"
        ),
        "provider_health_snapshot_hash": "health-old",
        "provider_eligibility_snapshot_hash": "eligibility-old",
        "rejected_candidates": [],
        "status": "WAITING_FOR_PROVIDER_AVAILABILITY",
        "MISSION_TERMINAL": False,
        "HUMAN_INTERVENTION_REQUIRED": False,
        "content_sha256": "wait-old",
    }
    health = {
        "schema": "ProviderHealthSnapshot/v1",
        "snapshot_ref": "objects/provider-health/new.json",
        "snapshot_sha256": "health-content-new",
        "material_state_sha256": "health-new",
        "observed_at": (
            NOW + timedelta(minutes=1)
        ).isoformat(),
        "eligible_zero_cost_provider_ids": ["nvidia_nim"],
        "HEALTH_ELIGIBLE_PROVIDER_COUNT": 1,
        "providers": [{
            "provider_id": "nvidia_nim",
            "state": "AVAILABLE",
            "zero_cost_eligible": True,
            "models": [
                {
                    "provider_id": "nvidia_nim",
                    "model_id": model_id,
                    "availability": "AVAILABLE",
                    "last_verified_at": (
                        NOW + timedelta(minutes=1)
                    ).isoformat(),
                    "source": "CURRENT_RUN_RUNTIME_PROOF",
                }
                for model_id in models
            ],
        }],
    }

    result = ProviderAvailabilityReconciler().reconcile(
        wait=wait,
        artifact_dir=tmp_path,
        now=NOW + timedelta(minutes=2),
        health_snapshot=health,
    )

    assert result["decision"] == "REQUEUE_TASK"
    assert result["new_effective_count"] > 0
    assert result["state_changed"] is True
    assert result["mission_id"] == "mission-real-path"
    assert result["task_id"] == "task-02"
    assert result["provider_recovery_epoch"]["epoch"] == 1
    assert result["recovered_provider_ids"] == ["nvidia_nim"]
    assert result["PROVIDER_CALLS_WHILE_WAITING"] == 0
    assert result["AGENT_TURNS_WHILE_WAITING"] == 0
    assert result["SEMANTIC_PLANNER_CALLS_WHILE_WAITING"] == 0
