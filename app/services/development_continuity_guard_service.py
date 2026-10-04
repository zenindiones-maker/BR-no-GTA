from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
import re

from app.services.development_continuity_policy_service import (
    DevelopmentContinuityPolicy,
    normalize_repo_path,
    validate_recovery_ref,
)


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_RECOVERY_OPERATIONS = frozenset(
    {
        "checkpoint",
        "recovery",
        "network_reconciliation",
        "secret_remediation",
        "safe_handoff_preparation",
    }
)


class DevelopmentDurabilityBlocked(RuntimeError):
    pass


class InventoryClassification(str, Enum):
    RECOVERABLE_SOURCE = "RECOVERABLE_SOURCE"
    LOCAL_RUNTIME_CONFIG = "LOCAL_RUNTIME_CONFIG"
    PRIVATE_SECRET = "PRIVATE_SECRET"
    LARGE_EVIDENCE = "LARGE_EVIDENCE"
    EPHEMERAL_GENERATED = "EPHEMERAL_GENERATED"


_EPHEMERAL_PREFIXES = (
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".coverage",
    "htmlcov/",
    "tmp/",
    ".tmp/",
)
_EPHEMERAL_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".swp",
    ".swo",
    "~",
)
_LOCAL_RUNTIME_CONFIG_NAMES = frozenset(
    {
        "config.yaml",
        "config.yml",
        "local.yaml",
        "local.yml",
        "runtime.yaml",
        "runtime.yml",
    }
)
_PRIVATE_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "secrets.yaml",
        "secrets.yml",
        "credentials.json",
    }
)
_PRIVATE_PREFIXES = (
    ".secrets/",
    "secrets/",
    "credentials/",
    ".credentials/",
    ".auth/",
    "private/",
    ".private/",
    "assets/private/",
)
_LARGE_PREFIXES = (
    "artifacts/",
    "logs/",
    "traces/",
    "diagnostics/",
    "coverage/",
)
_LARGE_SUFFIXES = (
    ".zip",
    ".tar",
    ".gz",
    ".mp4",
    ".mov",
    ".mkv",
    ".db",
    ".sqlite",
)


def _require_sha(value: str | None, *, field: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    normalized = str(value or "").strip().lower()
    if not _SHA40.fullmatch(normalized):
        raise ValueError(f"{field} must be a 40-character lowercase git oid")
    return normalized


def _utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


def classify_inventory_path(path: str, *, tracked: bool) -> InventoryClassification:
    value = normalize_repo_path(path)
    low = value.lower()
    name = PurePosixPath(low).name

    if low in _PRIVATE_NAMES or low.startswith(_PRIVATE_PREFIXES):
        return InventoryClassification.PRIVATE_SECRET
    if (
        "secret" in name
        or "credential" in name
        or name.endswith((".pem", ".key", ".p12", ".pfx"))
    ):
        return InventoryClassification.PRIVATE_SECRET
    if low.startswith(_LARGE_PREFIXES) or low.endswith(_LARGE_SUFFIXES):
        return InventoryClassification.LARGE_EVIDENCE
    if low.startswith(_EPHEMERAL_PREFIXES) or low.endswith(_EPHEMERAL_SUFFIXES):
        return InventoryClassification.EPHEMERAL_GENERATED
    if tracked:
        return InventoryClassification.RECOVERABLE_SOURCE
    if "/" not in value and low in _LOCAL_RUNTIME_CONFIG_NAMES:
        return InventoryClassification.LOCAL_RUNTIME_CONFIG
    if low.startswith(("app/", "tests/", "scripts/", ".github/", "docs/", "config/", "schemas/")):
        return InventoryClassification.RECOVERABLE_SOURCE
    return InventoryClassification.RECOVERABLE_SOURCE


@dataclass(frozen=True)
class DevelopmentDurabilityState:
    development_durability: str
    checkpoint_required: bool
    new_material_mutations_blocked: bool
    dirty_material_work: bool
    seconds_since_verified_remote: int
    reason: str


class DevelopmentContinuityGuard:
    schema_version = "DevelopmentContinuityGuard/v2"

    def __init__(self, policy: DevelopmentContinuityPolicy | None = None):
        self.policy = policy or DevelopmentContinuityPolicy()
        self._initialized = False
        self._mission_id: str | None = None
        self._canonical_branch: str | None = None
        self._canonical_base_sha: str | None = None
        self._recovery_ref: str | None = None
        self._expected_previous_remote_oid: str | None = None
        self._verified_remote_checkpoint_sha: str | None = None
        self._last_verified_remote_at: datetime | None = None
        self._dirty_since: datetime | None = None

    def initialize(
        self,
        *,
        mission_id: str,
        canonical_branch: str,
        canonical_base_sha: str,
        recovery_ref: str,
        expected_previous_remote_oid: str | None,
        verified_remote_checkpoint_sha: str | None,
        verified_at: datetime | None,
    ) -> None:
        mission = str(mission_id or "").strip()
        branch = str(canonical_branch or "").strip()
        if not mission:
            raise ValueError("mission_id is required")
        if not branch:
            raise ValueError("canonical_branch is required")
        self._mission_id = mission
        self._canonical_branch = branch
        self._canonical_base_sha = _require_sha(
            canonical_base_sha, field="canonical_base_sha"
        )
        self._recovery_ref = validate_recovery_ref(recovery_ref)
        self._expected_previous_remote_oid = _require_sha(
            expected_previous_remote_oid,
            field="expected_previous_remote_oid",
            allow_none=True,
        )
        self._verified_remote_checkpoint_sha = _require_sha(
            verified_remote_checkpoint_sha,
            field="verified_remote_checkpoint_sha",
            allow_none=True,
        )
        if self._verified_remote_checkpoint_sha is None:
            self._last_verified_remote_at = None
        else:
            if verified_at is None:
                raise ValueError("verified_at is required with a verified remote checkpoint")
            self._last_verified_remote_at = _utc(verified_at)
        self._initialized = True

    @property
    def initialized(self) -> bool:
        return self._initialized

    def mark_material_dirty(self, *, since: datetime | None = None) -> None:
        when = _utc(since)
        if self._dirty_since is None or when < self._dirty_since:
            self._dirty_since = when

    def mark_working_state_clean(self) -> None:
        self._dirty_since = None

    def mark_remote_checkpoint_verified(
        self, checkpoint_sha: str, *, verified_at: datetime | None = None
    ) -> None:
        if not self._initialized:
            raise DevelopmentDurabilityBlocked("CONTINUITY_NOT_INITIALIZED")
        self._verified_remote_checkpoint_sha = _require_sha(
            checkpoint_sha, field="checkpoint_sha"
        )
        self._last_verified_remote_at = _utc(verified_at)

    def durability_state(self, *, now: datetime | None = None) -> DevelopmentDurabilityState:
        current = _utc(now)
        if not self._initialized:
            return DevelopmentDurabilityState(
                development_durability="BLOCKED",
                checkpoint_required=True,
                new_material_mutations_blocked=True,
                dirty_material_work=self._dirty_since is not None,
                seconds_since_verified_remote=0,
                reason="CONTINUITY_NOT_INITIALIZED",
            )
        if self._dirty_since is None:
            return DevelopmentDurabilityState(
                development_durability="DURABLE",
                checkpoint_required=False,
                new_material_mutations_blocked=False,
                dirty_material_work=False,
                seconds_since_verified_remote=0,
                reason="NO_DIRTY_MATERIAL_WORK",
            )

        baseline = self._last_verified_remote_at or self._dirty_since
        seconds = max(0, int((current - baseline).total_seconds()))
        if self._last_verified_remote_at is None:
            seconds = max(0, int((current - self._dirty_since).total_seconds()))

        if seconds >= self.policy.rpo_hard_max_seconds:
            return DevelopmentDurabilityState(
                development_durability="DEGRADED",
                checkpoint_required=True,
                new_material_mutations_blocked=True,
                dirty_material_work=True,
                seconds_since_verified_remote=seconds,
                reason="RPO_HARD_MAX_REACHED",
            )
        if seconds >= self.policy.rpo_target_seconds:
            return DevelopmentDurabilityState(
                development_durability="CHECKPOINT_REQUIRED",
                checkpoint_required=True,
                new_material_mutations_blocked=False,
                dirty_material_work=True,
                seconds_since_verified_remote=seconds,
                reason="RPO_TARGET_REACHED",
            )
        return DevelopmentDurabilityState(
            development_durability="DIRTY_WITHIN_RPO",
            checkpoint_required=False,
            new_material_mutations_blocked=False,
            dirty_material_work=True,
            seconds_since_verified_remote=seconds,
            reason="RPO_WITHIN_TARGET",
        )

    def assert_material_mutation_allowed(
        self, *, now: datetime | None = None, operation: str = "material_mutation"
    ) -> None:
        state = self.durability_state(now=now)
        if state.reason == "CONTINUITY_NOT_INITIALIZED":
            raise DevelopmentDurabilityBlocked("CONTINUITY_NOT_INITIALIZED")
        if state.new_material_mutations_blocked and operation not in _ALLOWED_RECOVERY_OPERATIONS:
            raise DevelopmentDurabilityBlocked(
                f"RPO_HARD_MAX_REACHED: operation={operation}; checkpoint/recovery required"
            )

    def assert_terminal_state_allowed(
        self,
        *,
        terminal_state: str,
        working_state_clean: bool,
        intended_work_remote: bool,
        recovery_remote_readback_verified: bool,
    ) -> None:
        normalized = str(terminal_state or "").strip().upper()
        if normalized not in {"COMPLETED", "SUCCESS", "HANDOFF_READY", "SESSION_CLOSED"}:
            return
        clean_remote = bool(working_state_clean and intended_work_remote)
        recovery_remote = bool(recovery_remote_readback_verified)
        if not clean_remote and not recovery_remote:
            raise DevelopmentDurabilityBlocked(
                "DEVELOPMENT_DURABILITY_BLOCKED: terminal state requires remote representation"
            )