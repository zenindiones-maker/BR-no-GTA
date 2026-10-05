from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum


class ShutdownDecision(str, Enum):
    KEEP_INTERACTIVE = "KEEP_INTERACTIVE"
    KEEP_LEASE = "KEEP_LEASE"
    KEEP_PROTECTED_RENDER = "KEEP_PROTECTED_RENDER"
    KEEP_ACTIVE = "KEEP_ACTIVE"
    STOP_IDLE = "STOP_IDLE"
    STOP_MAX_RUNTIME = "STOP_MAX_RUNTIME"


def evaluate_shutdown(
    *,
    now: datetime,
    booted_at: datetime,
    last_activity_at: datetime,
    idle_timeout: timedelta,
    max_runtime: timedelta,
    interactive_active: bool,
    active_leases: int,
    protected_render_active: bool,
) -> ShutdownDecision:
    if protected_render_active:
        return ShutdownDecision.KEEP_PROTECTED_RENDER
    if active_leases > 0:
        return ShutdownDecision.KEEP_LEASE

    if now - booted_at >= max_runtime:
        return ShutdownDecision.STOP_MAX_RUNTIME

    if interactive_active:
        return ShutdownDecision.KEEP_INTERACTIVE

    if now - last_activity_at >= idle_timeout:
        return ShutdownDecision.STOP_IDLE

    return ShutdownDecision.KEEP_ACTIVE
