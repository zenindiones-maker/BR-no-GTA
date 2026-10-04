from __future__ import annotations

from enum import Enum


class DevelopmentDurabilityState(str, Enum):
    LOCAL_DIRTY = "LOCAL_DIRTY"
    LOCAL_CHECKPOINTED = "LOCAL_CHECKPOINTED"
    REMOTE_PUSH_PENDING = "REMOTE_PUSH_PENDING"
    REMOTE_DURABLE = "REMOTE_DURABLE"
    REMOTE_READBACK_VERIFIED = "REMOTE_READBACK_VERIFIED"
    DEGRADED_RECOVERY_REQUIRED = "DEGRADED_RECOVERY_REQUIRED"


def resolve_development_durability_state(
    *,
    worktree_dirty: bool,
    local_checkpoint_sha: str | None,
    push_attempted: bool,
    remote_checkpoint_sha: str | None,
    remote_readback_verified: bool,
    push_failed: bool,
) -> DevelopmentDurabilityState:
    local_sha = str(local_checkpoint_sha or "").strip()
    remote_sha = str(remote_checkpoint_sha or "").strip()

    if push_failed:
        return DevelopmentDurabilityState.DEGRADED_RECOVERY_REQUIRED
    if remote_readback_verified:
        if not local_sha or remote_sha != local_sha:
            return DevelopmentDurabilityState.DEGRADED_RECOVERY_REQUIRED
        return DevelopmentDurabilityState.REMOTE_READBACK_VERIFIED
    if local_sha and remote_sha == local_sha:
        return DevelopmentDurabilityState.REMOTE_DURABLE
    if local_sha and push_attempted:
        return DevelopmentDurabilityState.REMOTE_PUSH_PENDING
    if local_sha:
        return DevelopmentDurabilityState.LOCAL_CHECKPOINTED
    if worktree_dirty:
        return DevelopmentDurabilityState.LOCAL_DIRTY
    return DevelopmentDurabilityState.REMOTE_READBACK_VERIFIED
