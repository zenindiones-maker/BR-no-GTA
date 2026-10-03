from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "SpriteExecutionClassification/v1"
GRANT_SCHEMA = "ServiceExecutionGrant/v1"
ATTEMPT_SCHEMA = "SpriteExecutionAttempt/v1"

ONE_SHOT_TASK = "ONE_SHOT_TASK"
LONG_LIVED_SERVICE = "LONG_LIVED_SERVICE"
RESTART_BUDGET_EXHAUSTED = "RESTART_BUDGET_EXHAUSTED"

_ONE_SHOT_KINDS = frozenset({
    "tests", "test", "codeql", "zizmor", "osv", "independent_review",
    "review", "install", "bootstrap", "auth", "login", "migration",
    "canary", "diagnostics", "diagnostic",
})


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(_required(value, "timestamp").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_execution(task_kind: str) -> str:
    kind = _required(task_kind, "task_kind").lower().replace("-", "_")
    if kind in _ONE_SHOT_KINDS:
        return ONE_SHOT_TASK
    return LONG_LIVED_SERVICE


@dataclass(frozen=True)
class SpriteExecutionAttempt:
    task_kind: str
    sprite_id: str
    mission_id: str
    task_id: str
    attempt_id: str
    execution_class: str
    restart_policy: str
    max_restarts: int
    timeout_seconds: int
    terminal_status: str | None = None
    result_digest: str | None = None
    schema_version: str = ATTEMPT_SCHEMA

    @classmethod
    def one_shot(cls, *, task_kind: str, sprite_id: str, mission_id: str,
                 task_id: str, attempt_id: str, timeout_seconds: int) -> "SpriteExecutionAttempt":
        if classify_execution(task_kind) != ONE_SHOT_TASK:
            raise ValueError("task_kind is not classified as ONE_SHOT_TASK")
        if int(timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")
        return cls(
            task_kind=_required(task_kind, "task_kind"),
            sprite_id=_required(sprite_id, "sprite_id"),
            mission_id=_required(mission_id, "mission_id"),
            task_id=_required(task_id, "task_id"),
            attempt_id=_required(attempt_id, "attempt_id"),
            execution_class=ONE_SHOT_TASK,
            restart_policy="NEVER",
            max_restarts=0,
            timeout_seconds=int(timeout_seconds),
        )

    def assert_persistent_service_registration_allowed(self) -> None:
        if self.execution_class == ONE_SHOT_TASK:
            raise PermissionError("ONE_SHOT_TASK_NEVER_PERSISTENT_SERVICE")


@dataclass(frozen=True)
class ServiceExecutionGrant:
    authorization_id: str
    mission_id: str
    task_id: str
    sprite_id: str
    service_name: str
    service_class: str
    restart_policy: str
    max_restarts: int
    restart_window_seconds: int
    expires_at: str
    schema_version: str = GRANT_SCHEMA

    def validate(self, *, now: str) -> None:
        for field in ("authorization_id", "mission_id", "task_id", "sprite_id", "service_name"):
            _required(getattr(self, field), field)
        if self.service_class != LONG_LIVED_SERVICE:
            raise PermissionError("SERVICE_CREATION_DENIED: service_class must be LONG_LIVED_SERVICE")
        if self.restart_policy != "BOUNDED":
            raise PermissionError("SERVICE_CREATION_DENIED: restart_policy must be BOUNDED")
        if self.max_restarts < 0:
            raise ValueError("max_restarts must be >= 0")
        if self.restart_window_seconds <= 0:
            raise ValueError("restart_window_seconds must be positive")
        if _parse_time(now) >= _parse_time(self.expires_at):
            raise PermissionError("SERVICE_CREATION_DENIED: grant expired")


@dataclass(frozen=True)
class ServiceRuntimeState:
    grant: ServiceExecutionGrant
    service_creator: str
    attempt_id: str
    created_at: str
    restart_count: int = 0
    last_restart_at: str | None = None
    last_exit_code: int | None = None
    terminal_state: str | None = None
    return_to_harness: bool = False

    def audit_record(self) -> dict[str, Any]:
        return {
            "SERVICE_CREATOR": self.service_creator,
            "HARNESS_AUTHORIZATION_ID": self.grant.authorization_id,
            "MISSION_ID": self.grant.mission_id,
            "TASK_ID": self.grant.task_id,
            "ATTEMPT_ID": self.attempt_id,
            "CREATED_AT": self.created_at,
            "RESTART_POLICY": self.grant.restart_policy,
            "RESTART_COUNT": self.restart_count,
            "LAST_EXIT_CODE": self.last_exit_code,
        }


def _authorization_matches(grant: ServiceExecutionGrant, authorization: Mapping[str, Any] | None) -> bool:
    if not authorization:
        return False
    return all((
        str(authorization.get("authorization_id") or "") == grant.authorization_id,
        str(authorization.get("issued_by") or "") == "deepseek_harness",
        str(authorization.get("status") or "") == "active",
        str(authorization.get("subject") or "") == f"service:{grant.service_name}",
        str(authorization.get("mission_id") or "") == grant.mission_id,
        str(authorization.get("task_id") or "") == grant.task_id,
    ))


def authorize_service_creation(*, grant: ServiceExecutionGrant,
                               harness_authorization: Mapping[str, Any] | None,
                               now: str, service_creator: str = "DeepSeek Harness",
                               attempt_id: str | None = None) -> ServiceRuntimeState:
    grant.validate(now=now)
    if not _authorization_matches(grant, harness_authorization):
        raise PermissionError("SERVICE_CREATION_DENIED: valid DeepSeek Harness authorization required")
    return ServiceRuntimeState(
        grant=grant,
        service_creator=_required(service_creator, "service_creator"),
        attempt_id=_required(attempt_id or grant.task_id, "attempt_id"),
        created_at=_required(now, "created_at"),
    )


def request_service_restart(runtime: ServiceRuntimeState, *, last_exit_code: int,
                            now: str) -> ServiceRuntimeState:
    if runtime.terminal_state is not None:
        return runtime
    runtime.grant.validate(now=now)
    current = _parse_time(now)
    window_anchor = _parse_time(runtime.last_restart_at or runtime.created_at)
    restart_count = runtime.restart_count
    if (current - window_anchor).total_seconds() > runtime.grant.restart_window_seconds:
        restart_count = 0
    if restart_count >= runtime.grant.max_restarts:
        return replace(
            runtime,
            last_exit_code=int(last_exit_code),
            terminal_state=RESTART_BUDGET_EXHAUSTED,
            return_to_harness=True,
        )
    return replace(
        runtime,
        restart_count=restart_count + 1,
        last_restart_at=now,
        last_exit_code=int(last_exit_code),
    )
