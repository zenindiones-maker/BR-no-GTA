from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.services.openai_agents_contracts import AgentEnvironmentLease


def _require_text(value: str, name: str, maximum: int = 512) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return text


def _require_sha(value: str, name: str) -> str:
    text = _require_text(value, name, 64)
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{name} must be a lowercase 40-character git SHA")
    return text


@dataclass(frozen=True)
class AgentEnvironmentAcquireRequest:
    environment_lease: AgentEnvironmentLease
    mission_id: str
    goal_id: str
    task_id: str
    attempt_id: str
    openai_session_id: str
    openai_environment_id: str
    workspace: str
    repo_sha: str
    tree_sha: str
    mutating: bool
    schema: str = "AgentEnvironmentAcquireRequest/v1"

    def __post_init__(self) -> None:
        self.environment_lease.assert_active()
        if self.environment_lease.environment_type != "SPRITE":
            raise PermissionError("AgentEnvironmentProvider requires a SPRITE lease")
        _require_text(self.mission_id, "mission_id")
        _require_text(self.goal_id, "goal_id")
        _require_text(self.task_id, "task_id")
        _require_text(self.attempt_id, "attempt_id")
        _require_text(self.openai_session_id, "openai_session_id")
        _require_text(self.openai_environment_id, "openai_environment_id")
        workspace = _require_text(self.workspace, "workspace", 1024)
        if not workspace.startswith("/"):
            raise ValueError("workspace must be an absolute path")
        _require_sha(self.repo_sha, "repo_sha")
        _require_sha(self.tree_sha, "tree_sha")
        expected_task_ref = f"delegated-task:{self.task_id}"
        if self.environment_lease.task_lease_ref != expected_task_ref:
            raise PermissionError("environment lease task binding mismatch")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentEnvironmentProvider(Protocol):
    provider_id: str

    def acquire(self, request: AgentEnvironmentAcquireRequest) -> Any:
        ...

    def reconnect(self, binding_id: str) -> Any:
        ...

    def checkpoint(self, binding_id: str) -> Any:
        ...

    def release(self, binding_id: str) -> Any:
        ...


def assert_environment_binding_fresh(
    *,
    expires_at: str,
    status: str,
    now: datetime | None = None,
) -> None:
    if str(status or "").upper() != "ACTIVE":
        raise PermissionError("environment binding is not active")
    expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    current = now or datetime.now(timezone.utc)
    if expiry.tzinfo is None:
        raise ValueError("environment binding expiry must include timezone")
    if current >= expiry:
        raise PermissionError("environment binding expired")


__all__ = [
    "AgentEnvironmentAcquireRequest",
    "AgentEnvironmentProvider",
    "assert_environment_binding_fresh",
]
