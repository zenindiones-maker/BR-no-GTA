from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping
from uuid import uuid4

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
MANDATORY_FORBIDDEN_ACTIONS = frozenset({
    "push",
    "merge",
    "canonical_branch_write",
    "policy_mutation",
    "authority_mutation",
    "secret_access",
    "credential_access",
    "destructive_database_migration",
    "external_paid_action",
    "youtube_publish_public",
})


def _text(value: Any, name: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    result = value.strip()
    if len(result) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return result


def _identifier(value: Any, name: str) -> str:
    result = _text(value, name, maximum=192)
    if not _ID_RE.fullmatch(result):
        raise ValueError(f"{name} contains invalid characters")
    return result


def _tuple(value: Any, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if value is None and allow_empty:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list")
    result = tuple(_text(item, name, maximum=1000) for item in value)
    if not allow_empty and not result:
        raise ValueError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return result


def _paths(value: Any, name: str) -> tuple[str, ...]:
    result = _tuple(value, name)
    for item in result:
        normalized = item.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError(f"{name} contains an unsafe path")
    return result


def _positive_int(value: Any, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [0, {maximum}]")
    return value


@dataclass(frozen=True)
class DelegatedTaskLease:
    mission_id: str
    task_id: str
    goal_id: str
    harness_decision_id: str
    authorization_id: str
    delegation_id: str
    agent_id: str
    capability_ids: tuple[str, ...]
    base_sha: str
    allowed_paths: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    input_artifact_refs: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    time_budget_seconds: int
    cost_budget: float
    tool_call_budget: int
    retry_budget: int
    max_parallelism: int
    expires_at: str
    escalation_conditions: tuple[str, ...]
    owned_task_class: str
    role: str
    read_set: tuple[str, ...] = ()
    write_set: tuple[str, ...] = ()
    parent_task_id: str | None = None
    authority: str = "DELEGATED_ONLY"
    canonical_push_authority: str = "NONE"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DelegatedTaskLease":
        if not isinstance(value, Mapping):
            raise ValueError("DelegatedTaskLease must be an object")
        sha = _text(value.get("base_sha"), "base_sha", maximum=40).lower()
        if not _SHA_RE.fullmatch(sha):
            raise ValueError("base_sha must be a full lowercase commit SHA")
        forbidden = _tuple(value.get("forbidden_actions"), "forbidden_actions", allow_empty=False)
        missing = MANDATORY_FORBIDDEN_ACTIONS.difference(forbidden)
        if missing:
            raise ValueError(f"forbidden_actions missing mandatory boundaries: {sorted(missing)}")
        allowed_paths = _paths(value.get("allowed_paths"), "allowed_paths")
        write_set = _paths(value.get("write_set"), "write_set")
        if write_set and not allowed_paths:
            raise ValueError("write_set requires explicit allowed_paths")
        for path in write_set:
            if not any(path == allowed or path.startswith(f"{allowed.rstrip('/')}/") for allowed in allowed_paths):
                raise ValueError("write_set escapes allowed_paths")
        expires_at = _text(value.get("expires_at"), "expires_at", maximum=64)
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("expires_at must be ISO-8601") from exc
        if expiry.tzinfo is None:
            raise ValueError("expires_at must include timezone")
        cost = value.get("cost_budget")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
            raise ValueError("cost_budget must be non-negative")
        parent = value.get("parent_task_id")
        return cls(
            mission_id=_identifier(value.get("mission_id"), "mission_id"),
            task_id=_identifier(value.get("task_id"), "task_id"),
            goal_id=_identifier(value.get("goal_id"), "goal_id"),
            harness_decision_id=_identifier(value.get("harness_decision_id"), "harness_decision_id"),
            authorization_id=_identifier(value.get("authorization_id"), "authorization_id"),
            delegation_id=_identifier(value.get("delegation_id"), "delegation_id"),
            agent_id=_identifier(value.get("agent_id"), "agent_id"),
            capability_ids=_tuple(value.get("capability_ids"), "capability_ids", allow_empty=False),
            base_sha=sha,
            allowed_paths=allowed_paths,
            allowed_tools=_tuple(value.get("allowed_tools"), "allowed_tools", allow_empty=False),
            allowed_actions=_tuple(value.get("allowed_actions"), "allowed_actions", allow_empty=False),
            forbidden_actions=forbidden,
            input_artifact_refs=_tuple(value.get("input_artifact_refs"), "input_artifact_refs"),
            expected_outputs=_tuple(value.get("expected_outputs"), "expected_outputs", allow_empty=False),
            acceptance_criteria=_tuple(value.get("acceptance_criteria"), "acceptance_criteria", allow_empty=False),
            evidence_requirements=_tuple(value.get("evidence_requirements"), "evidence_requirements", allow_empty=False),
            time_budget_seconds=_positive_int(value.get("time_budget_seconds"), "time_budget_seconds", maximum=7200),
            cost_budget=float(cost),
            tool_call_budget=_positive_int(value.get("tool_call_budget"), "tool_call_budget", maximum=1000),
            retry_budget=_positive_int(value.get("retry_budget"), "retry_budget", maximum=20),
            max_parallelism=_positive_int(value.get("max_parallelism"), "max_parallelism", maximum=32),
            expires_at=expires_at,
            escalation_conditions=_tuple(value.get("escalation_conditions"), "escalation_conditions", allow_empty=False),
            owned_task_class=_identifier(value.get("owned_task_class"), "owned_task_class"),
            role=_identifier(value.get("role"), "role"),
            read_set=_paths(value.get("read_set"), "read_set"),
            write_set=write_set,
            parent_task_id=None if parent in (None, "") else _identifier(parent, "parent_task_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def assert_active(self, *, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if current >= expiry:
            raise PermissionError("delegated task lease expired")

    def allows_path(self, path: str, *, write: bool = False) -> bool:
        normalized = path.replace("\\", "/").strip("/")
        allowed = self.write_set if write else (self.read_set or self.allowed_paths)
        return any(
            normalized == item.strip("/") or normalized.startswith(f"{item.strip('/')}/")
            for item in allowed
            if item.strip("/")
        )


def write_conflicts(leases: tuple[DelegatedTaskLease, ...]) -> tuple[tuple[str, str, str], ...]:
    conflicts: list[tuple[str, str, str]] = []
    for index, left in enumerate(leases):
        for right in leases[index + 1:]:
            for a in left.write_set:
                for b in right.write_set:
                    aa, bb = a.rstrip("/"), b.rstrip("/")
                    if aa == bb or aa.startswith(f"{bb}/") or bb.startswith(f"{aa}/"):
                        conflicts.append((left.task_id, right.task_id, aa if len(aa) <= len(bb) else bb))
    return tuple(sorted(set(conflicts)))


def new_delegation_id(mission_id: str, task_id: str) -> str:
    return f"delegation:{mission_id}:{task_id}:{uuid4().hex[:12]}"
