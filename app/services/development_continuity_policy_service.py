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
