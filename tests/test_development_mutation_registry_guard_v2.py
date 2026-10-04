from pathlib import Path

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY


EXPECTED_MUTATORS = {
    "agent-office.execute": (
        "app.services.agent_office_harness_service.execute_agent_office_capability"
    ),
    "agent-office.codex.bounded-development": (
        "app.services.agent_office_harness_service.execute_authorized_agent_office_specialist"
    ),
    "development.checkpoint.persist": (
        "app.services.development_checkpoint_capability_service."
        "execute_development_checkpoint_persist_capability"
    ),
    "development.canonical.promotion-authorize": (
        "app.services.canonical_promotion_authorization_service."
        "issue_exact_canonical_promotion_authorization"
    ),
    "harness.recovery.apply-local": (
        "app.services.recovery_execution_service.execute_recovery_apply_capability"
    ),
}


def test_all_registered_bounded_mutators_are_explicitly_governed():
    records = {
        record.capability_id: record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.side_effect_class == "BOUNDED_MUTATION"
    }
    assert set(records) == set(EXPECTED_MUTATORS)
    for capability_id, expected_binding in EXPECTED_MUTATORS.items():
        assert records[capability_id].executor_binding == expected_binding


def test_mutating_executor_bindings_contain_durability_boundaries():
    root = Path(__file__).resolve().parents[1]
    office = (root / "app/services/agent_office_harness_service.py").read_text()
    recovery = (root / "app/services/recovery_execution_service.py").read_text()
    checkpoint = (
        root / "app/services/development_checkpoint_capability_service.py"
    ).read_text()
    recovery_checkpoint = (
        root / "app/services/development_recovery_checkpoint_service.py"
    ).read_text()
    promotion_authority = (
        root / "app/services/canonical_promotion_authorization_service.py"
    ).read_text()

    assert "HarnessDevelopmentCheckpointHook" in office
    assert "development_durability_hook=durability_hook" in office
    assert "execute_authorized_agent_office(" in office

    assert "DEVELOPMENT_CONTINUITY_REQUIRED" in recovery
    assert "BEFORE_FIRST_RISKY_MUTATION" in recovery
    assert "AFTER_ATOMIC_TASK_COMPLETION" in recovery
    assert "DEVELOPMENT_PROGRESS_DURABLE" in recovery

    assert 'CAPABILITY_ID = "development.checkpoint.persist"' in checkpoint
    assert "DevelopmentRecoveryCheckpointService" in checkpoint
    assert "remote_readback_status" in recovery_checkpoint
    assert "_trusted_control_identity" in promotion_authority
    assert "validate_harness_authorization" in promotion_authority
    assert "route_harness_request" in promotion_authority
    assert "CANONICAL_PROMOTION_SECURITY_REVIEW_NOT_PASS" in promotion_authority
