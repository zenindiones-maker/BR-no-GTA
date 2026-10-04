from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.development_continuity_guard_service import (
    DevelopmentContinuityGuard,
    DevelopmentDurabilityBlocked,
    InventoryClassification,
    classify_inventory_path,
)


def _now() -> datetime:
    return datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def test_guard_blocks_material_mutation_before_continuity_initialization():
    guard = DevelopmentContinuityGuard()
    with pytest.raises(DevelopmentDurabilityBlocked, match="CONTINUITY_NOT_INITIALIZED"):
        guard.assert_material_mutation_allowed(now=_now())


def test_guard_requires_checkpoint_at_target_rpo_and_blocks_new_mutation_at_hard_max():
    guard = DevelopmentContinuityGuard()
    guard.initialize(
        mission_id="mission-1",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="c" * 40,
        recovery_ref="recovery/dev/mission-1",
        expected_previous_remote_oid="a" * 40,
        verified_remote_checkpoint_sha="a" * 40,
        verified_at=_now() - timedelta(seconds=301),
    )
    guard.mark_material_dirty(since=_now() - timedelta(seconds=301))
    state = guard.durability_state(now=_now())
    assert state.checkpoint_required is True
    assert state.new_material_mutations_blocked is False

    guard.mark_remote_checkpoint_verified("b" * 40, verified_at=_now() - timedelta(seconds=601))
    guard.mark_material_dirty(since=_now() - timedelta(seconds=601))
    state = guard.durability_state(now=_now())
    assert state.development_durability == "DEGRADED"
    assert state.new_material_mutations_blocked is True
    with pytest.raises(DevelopmentDurabilityBlocked, match="RPO_HARD_MAX_REACHED"):
        guard.assert_material_mutation_allowed(now=_now())

    guard.assert_material_mutation_allowed(now=_now(), operation="checkpoint")


def test_terminal_success_is_forbidden_with_local_only_material_progress():
    guard = DevelopmentContinuityGuard()
    guard.initialize(
        mission_id="mission-2",
        canonical_branch="work/gate6f-analytics-learning",
        canonical_base_sha="c" * 40,
        recovery_ref="recovery/dev/mission-2",
        expected_previous_remote_oid=None,
        verified_remote_checkpoint_sha="d" * 40,
        verified_at=_now(),
    )
    guard.mark_material_dirty(since=_now())
    with pytest.raises(DevelopmentDurabilityBlocked, match="DEVELOPMENT_DURABILITY_BLOCKED"):
        guard.assert_terminal_state_allowed(
            terminal_state="COMPLETED",
            working_state_clean=False,
            intended_work_remote=False,
            recovery_remote_readback_verified=False,
        )
    guard.assert_terminal_state_allowed(
        terminal_state="COMPLETED",
        working_state_clean=False,
        intended_work_remote=False,
        recovery_remote_readback_verified=True,
    )


@pytest.mark.parametrize(
    ("path", "tracked", "expected"),
    [
        ("app/services/example.py", False, InventoryClassification.RECOVERABLE_SOURCE),
        ("config.yaml", False, InventoryClassification.LOCAL_RUNTIME_CONFIG),
        (".env", False, InventoryClassification.PRIVATE_SECRET),
        ("artifacts/result.zip", False, InventoryClassification.LARGE_EVIDENCE),
        ("__pycache__/x.pyc", False, InventoryClassification.EPHEMERAL_GENERATED),
        ("config/source.yaml", True, InventoryClassification.RECOVERABLE_SOURCE),
    ],
)
def test_inventory_classification_is_explicit(path, tracked, expected):
    assert classify_inventory_path(path, tracked=tracked) is expected
