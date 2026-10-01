from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re

_RECOVERY_REF = re.compile(r"^recovery/dev/[a-z0-9][a-z0-9._/-]{0,120}$")

PRIVATE_PREFIXES = (
    ".env", ".secrets", "secrets/", "credentials/", ".credentials/",
    "assets/private/", "private/", ".private/", ".auth/", ".cache/tokens/",
)
LARGE_PREFIXES = ("coverage/", "artifacts/", "logs/", "traces/", "diagnostics/", "tmp/")
RECOVERABLE_PREFIXES = (
    "app/", "tests/", "scripts/", ".github/", "docs/", "config/", "schemas/",
    ".development-recovery/",
)


@dataclass(frozen=True)
class DevelopmentContinuityPolicy:
    required: bool = True
    rpo_target_seconds: int = 300
    rpo_hard_max_seconds: int = 600
    resume_rto_target_seconds: int = 600
    heartbeat_interval_seconds: int = 90
    remote_checkpoint_required_before_handoff: bool = True
    remote_checkpoint_required_before_session_end: bool = True
    remote_checkpoint_required_before_environment_destruction: bool = True
    pre_risk_checkpoint_required: bool = True
    remote_read_after_write_required: bool = True
    recovery_ref_fast_forward_only: bool = True
    force_push_recovery: bool = False
    recovery_ref_can_trigger_production: bool = False
    canonical_branch_wip_autosave: bool = False
    side_effect_replay_from_dev_checkpoint: bool = False
    checkpoint_history_in_canonical: bool = False


def normalize_repo_path(path: str) -> str:
    raw = str(path).replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    value = str(PurePosixPath(raw))
    if value in {"", "."} or value.startswith("../"):
        raise ValueError(f"invalid repository path: {path!r}")
    return value


def validate_recovery_ref(ref: str) -> str:
    value = str(ref or "").strip()
    if not _RECOVERY_REF.fullmatch(value):
        raise ValueError("recovery ref must be under recovery/dev/** and sanitized")
    if ".." in value.split("/"):
        raise ValueError("recovery ref cannot contain parent traversal")
    return value


def classify_path(path: str) -> str:
    value = normalize_repo_path(path)
    low = value.lower()
    if low == ".env" or low.startswith(PRIVATE_PREFIXES):
        return "PRIVATE_FORBIDDEN"
    secretish = ("/token" in low or low.endswith(".pem") or low.endswith(".key")
                 or "credentials" in low or "secret" in low)
    if secretish:
        return "PRIVATE_FORBIDDEN"
    if low.startswith(LARGE_PREFIXES) or low.endswith((".sqlite", ".db", ".mp4", ".mov", ".zip", ".tar", ".gz")):
        return "LARGE_EVIDENCE"
    if low.startswith(RECOVERABLE_PREFIXES) or low in {"agents.md", "requirements.txt", "pytest.ini", "pyproject.toml"}:
        return "RECOVERABLE_SOURCE"
    return "UNCLASSIFIED"


def recovery_gc_state(
    *, promoted: bool, current_head_verified: bool,
    evidence_resolvable: bool, retention_elapsed: bool,
) -> str:
    if not promoted:
        return "ACTIVE"
    if not current_head_verified:
        return "PROMOTED"
    if not retention_elapsed or not evidence_resolvable:
        return "RETENTION_WINDOW"
    return "GC_ELIGIBLE"


SEMANTIC_CHECKPOINT_EVENTS = frozenset({
    "BEFORE_FIRST_RISKY_MUTATION",
    "AFTER_ATOMIC_TASK_COMPLETION",
    "AFTER_CAUSAL_DIAGNOSIS",
    "AFTER_SIGNIFICANT_IMPLEMENTATION",
    "BEFORE_LONG_VALIDATION",
    "AFTER_MATERIAL_VALIDATION",
    "BEFORE_AGENT_HANDOFF",
    "BEFORE_ENVIRONMENT_SWITCH",
    "BEFORE_SESSION_SHUTDOWN",
    "BEFORE_ENVIRONMENT_DESTRUCTION",
    "BEFORE_HUMAN_WAIT_WITH_DIRTY_WORK",
    "CONTEXT_EXHAUSTION_APPROACHING",
    "AFTER_MAJOR_GATE_CLOSURE",
})


@dataclass(frozen=True)
class CheckpointTriggerDecision:
    should_checkpoint: bool
    mandatory: bool
    reason: str
    run_tests: bool = False
    implies_durability: bool = False


def checkpoint_trigger_decision(
    *,
    event: str,
    dirty: bool,
    seconds_since_verified_remote: int,
    policy: DevelopmentContinuityPolicy | None = None,
) -> CheckpointTriggerDecision:
    p = policy or DevelopmentContinuityPolicy()
    normalized = str(event or "").strip().upper()
    if normalized == "HEARTBEAT":
        return CheckpointTriggerDecision(False, False, "HEARTBEAT_LIVENESS_ONLY")
    if not dirty:
        return CheckpointTriggerDecision(False, False, "NO_DIRTY_MATERIAL_WORK")
    if normalized in SEMANTIC_CHECKPOINT_EVENTS:
        mandatory = normalized in {
            "BEFORE_AGENT_HANDOFF",
            "BEFORE_SESSION_SHUTDOWN",
            "BEFORE_ENVIRONMENT_DESTRUCTION",
            "BEFORE_FIRST_RISKY_MUTATION",
        }
        return CheckpointTriggerDecision(True, mandatory, normalized)
    if normalized == "WATCHDOG":
        age = max(0, int(seconds_since_verified_remote))
        if age >= p.rpo_hard_max_seconds:
            return CheckpointTriggerDecision(True, True, "RPO_HARD_MAX_REACHED")
        if age >= p.rpo_target_seconds:
            return CheckpointTriggerDecision(True, False, "RPO_TARGET_REACHED")
        return CheckpointTriggerDecision(False, False, "RPO_WITHIN_TARGET")
    return CheckpointTriggerDecision(False, False, "NO_SEMANTIC_CHECKPOINT_TRIGGER")
