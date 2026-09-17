from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Mapping


COORDINATOR_ROLE = "AGENT_OFFICE_COORDINATOR"
DELEGATED_AUTHORITY = "DELEGATED_ONLY"
ALLOWED_ACTIONS = {"DEVELOPMENT"}
MANDATORY_FORBIDDEN_ACTIONS = {
    "youtube_publish",
    "autonomous_schedule",
    "secret_access",
    "policy_mutation",
}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def _required_text(value: Any, field_name: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")
    return normalized


def _identifier(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name, maximum=128)
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} contains invalid characters")
    return normalized


def _string_tuple(value: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    normalized = tuple(_required_text(item, field_name, maximum=500) for item in value)
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


@dataclass(frozen=True)
class AgentOfficeTask:
    task_id: str
    agent: str
    capability: str
    action: str
    objective: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgentOfficeTask":
        if not isinstance(value, Mapping):
            raise ValueError("task must be an object")
        return cls(
            task_id=_identifier(value.get("task_id"), "task_id"),
            agent=_identifier(value.get("agent"), "agent"),
            capability=_identifier(value.get("capability"), "capability"),
            action=_identifier(value.get("action"), "action").lower(),
            objective=_required_text(value.get("objective"), "objective", maximum=4_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentOfficeExecutionSpec:
    execution_id: str
    goal_id: str
    brain_decision_id: str
    harness_authorization_id: str
    authorized_action: str
    task_type: str
    repository: str
    branch: str
    base_sha: str
    allowed_agents: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    max_parallelism: int
    time_budget_seconds: int
    cost_budget: float
    expected_outputs: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    coordinator_role: str = COORDINATOR_ROLE
    authority: str = DELEGATED_AUTHORITY

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgentOfficeExecutionSpec":
        if not isinstance(value, Mapping):
            raise ValueError("AgentOfficeExecutionSpec must be an object")
        action = _required_text(value.get("authorized_action"), "authorized_action").upper()
        if action not in ALLOWED_ACTIONS:
            raise ValueError("authorized_action is not permitted for Agent Office")
        sha = _required_text(value.get("base_sha"), "base_sha", maximum=40).lower()
        if not _SHA_RE.fullmatch(sha):
            raise ValueError("base_sha must be a full lowercase commit SHA")
        parallelism = value.get("max_parallelism")
        if isinstance(parallelism, bool) or not isinstance(parallelism, int) or not 1 <= parallelism <= 8:
            raise ValueError("max_parallelism must be an integer in [1, 8]")
        time_budget = value.get("time_budget_seconds")
        if isinstance(time_budget, bool) or not isinstance(time_budget, int) or not 1 <= time_budget <= 7_200:
            raise ValueError("time_budget_seconds must be an integer in [1, 7200]")
        cost_budget = value.get("cost_budget")
        if isinstance(cost_budget, bool) or not isinstance(cost_budget, (int, float)) or cost_budget < 0:
            raise ValueError("cost_budget must be a non-negative number")
        forbidden = _string_tuple(value.get("forbidden_actions"), "forbidden_actions")
        missing = MANDATORY_FORBIDDEN_ACTIONS.difference(forbidden)
        if missing:
            raise ValueError("forbidden_actions is missing mandatory safety boundaries")

        allowed_paths = _string_tuple(value.get("allowed_paths"), "allowed_paths", allow_empty=True)
        for path in allowed_paths:
            if path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/"):
                raise ValueError("allowed_paths must be repository-relative and traversal-free")

        return cls(
            execution_id=_identifier(value.get("execution_id"), "execution_id"),
            goal_id=_identifier(value.get("goal_id"), "goal_id"),
            brain_decision_id=_identifier(value.get("brain_decision_id"), "brain_decision_id"),
            harness_authorization_id=_identifier(
                value.get("harness_authorization_id"), "harness_authorization_id"
            ),
            authorized_action=action,
            task_type=_identifier(value.get("task_type"), "task_type").upper(),
            repository=_required_text(value.get("repository"), "repository", maximum=200),
            branch=_required_text(value.get("branch"), "branch", maximum=200),
            base_sha=sha,
            allowed_agents=_string_tuple(value.get("allowed_agents"), "allowed_agents"),
            allowed_capabilities=_string_tuple(
                value.get("allowed_capabilities"), "allowed_capabilities"
            ),
            allowed_paths=allowed_paths,
            forbidden_actions=forbidden,
            max_parallelism=parallelism,
            time_budget_seconds=time_budget,
            cost_budget=float(cost_budget),
            expected_outputs=_string_tuple(value.get("expected_outputs"), "expected_outputs"),
            evidence_requirements=_string_tuple(
                value.get("evidence_requirements"), "evidence_requirements"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentOfficeExecutionResult:
    execution_id: str
    status: str
    started_at: str
    finished_at: str
    agents_used: tuple[str, ...]
    tasks: tuple[dict[str, Any], ...]
    per_agent_results: tuple[dict[str, Any], ...]
    files_changed: tuple[str, ...]
    commits: tuple[str, ...]
    tests: tuple[dict[str, Any], ...]
    commands_evidence: tuple[str, ...]
    artifacts: tuple[str, ...]
    errors: tuple[str, ...]
    usage: dict[str, Any]
    final_summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    coordinator_role: str = COORDINATOR_ROLE
    authority: str = DELEGATED_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
