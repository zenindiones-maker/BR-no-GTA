from app.services.development_durability_state_service import (
    DevelopmentDurabilityState,
    resolve_development_durability_state,
)


def test_required_development_durability_states_are_distinct():
    resolve = resolve_development_durability_state
    cases = [
        (dict(worktree_dirty=True, local_checkpoint_sha=None, push_attempted=False, remote_checkpoint_sha=None, remote_readback_verified=False, push_failed=False), DevelopmentDurabilityState.LOCAL_DIRTY),
        (dict(worktree_dirty=True, local_checkpoint_sha="a"*40, push_attempted=False, remote_checkpoint_sha=None, remote_readback_verified=False, push_failed=False), DevelopmentDurabilityState.LOCAL_CHECKPOINTED),
        (dict(worktree_dirty=True, local_checkpoint_sha="a"*40, push_attempted=True, remote_checkpoint_sha=None, remote_readback_verified=False, push_failed=False), DevelopmentDurabilityState.REMOTE_PUSH_PENDING),
        (dict(worktree_dirty=True, local_checkpoint_sha="a"*40, push_attempted=True, remote_checkpoint_sha="a"*40, remote_readback_verified=False, push_failed=False), DevelopmentDurabilityState.REMOTE_DURABLE),
        (dict(worktree_dirty=True, local_checkpoint_sha="a"*40, push_attempted=True, remote_checkpoint_sha="a"*40, remote_readback_verified=True, push_failed=False), DevelopmentDurabilityState.REMOTE_READBACK_VERIFIED),
        (dict(worktree_dirty=True, local_checkpoint_sha="a"*40, push_attempted=True, remote_checkpoint_sha=None, remote_readback_verified=False, push_failed=True), DevelopmentDurabilityState.DEGRADED_RECOVERY_REQUIRED),
    ]
    for kwargs, expected in cases:
        assert resolve(**kwargs) is expected


def test_verified_state_fails_closed_on_sha_mismatch():
    assert resolve_development_durability_state(
        worktree_dirty=False,
        local_checkpoint_sha="a"*40,
        push_attempted=True,
        remote_checkpoint_sha="b"*40,
        remote_readback_verified=True,
        push_failed=False,
    ) is DevelopmentDurabilityState.DEGRADED_RECOVERY_REQUIRED
