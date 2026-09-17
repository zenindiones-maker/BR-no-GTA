from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal


ValidationLevel = Literal["STRUCTURAL", "LIVE"]
ReceiptStatus = Literal[
    "PENDING",
    "READY",
    "RUNNING",
    "WAITING_DEPENDENCY",
    "WAITING_REVIEW",
    "WAITING_HUMAN",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "BLOCKED",
]
CoverageStatus = Literal[
    "PROVEN_LIVE",
    "PROVEN_STRUCTURAL",
    "AVAILABLE_UNEXERCISED",
    "PARTIAL",
    "DEGRADED_EXTERNAL_BLOCKER",
    "BLOCKED",
    "UNPROVEN",
]

_TERMINAL_SUCCESS = {"COMPLETED"}
_TERMINAL_FAILURE = {"FAILED", "CANCELLED", "BLOCKED"}


def _require_text(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _refs(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in values if str(value).strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError("evidence/input/output refs must be unique")
    return normalized


@dataclass(frozen=True)
class AgentInvocationReceipt:
    """Auditable proof that a routed implementation was actually invoked.

    Registry membership and routing are intentionally insufficient. A receipt only
    becomes PROVEN_LIVE when the execution itself completed, produced evidence and
    returned to the DeepSeek Harness under a LIVE validation level.
    """

    mission_id: str
    task_id: str
    goal_id: str
    decision_id: str
    authorization_id: str
    agent_id: str
    capability: str
    executor: str
    provider: str
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    started_at: str = ""
    finished_at: str = ""
    status: ReceiptStatus = "PENDING"
    validation_level: ValidationLevel = "STRUCTURAL"
    skill_id: str | None = None
    external_call_performed: bool = False
    exit_code: int | None = None
    latency_seconds: float | None = None
    error: str | None = None
    returned_to_harness: bool = False

    def __post_init__(self) -> None:
        for name in (
            "mission_id",
            "task_id",
            "goal_id",
            "decision_id",
            "authorization_id",
            "agent_id",
            "capability",
            "executor",
            "provider",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "input_refs", _refs(self.input_refs))
        object.__setattr__(self, "output_refs", _refs(self.output_refs))
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs))
        if self.status not in ReceiptStatus.__args__:
            raise ValueError(f"invalid receipt status: {self.status}")
        if self.validation_level not in ValidationLevel.__args__:
            raise ValueError(f"invalid validation level: {self.validation_level}")
        if self.latency_seconds is not None and self.latency_seconds < 0:
            raise ValueError("latency_seconds cannot be negative")
        if self.status == "COMPLETED":
            if not self.finished_at:
                raise ValueError("completed receipt requires finished_at")
            if not self.evidence_refs:
                raise ValueError("completed receipt requires evidence_refs")
            if not self.output_refs:
                raise ValueError("completed receipt requires output_refs")
            if not self.returned_to_harness:
                raise ValueError("completed receipt must return to Harness")
        if self.status in _TERMINAL_FAILURE and not self.finished_at:
            raise ValueError("terminal receipt requires finished_at")

    @property
    def proven_live(self) -> bool:
        return bool(
            self.validation_level == "LIVE"
            and self.status in _TERMINAL_SUCCESS
            and self.returned_to_harness
            and self.output_refs
            and self.evidence_refs
        )

    @property
    def proven_structural(self) -> bool:
        return bool(
            self.validation_level == "STRUCTURAL"
            and self.status in _TERMINAL_SUCCESS
            and self.returned_to_harness
            and self.output_refs
            and self.evidence_refs
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["proven_live"] = self.proven_live
        data["proven_structural"] = self.proven_structural
        return data


@dataclass(frozen=True)
class SwarmTask:
    task_id: str
    capability: str
    agent_id: str
    dependencies: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    expected_output: str = ""
    review_required: bool = False
    authorization_scope: str = "EXECUTION"
    status: ReceiptStatus = "PENDING"
    retry_limit: int = 0
    timeout_seconds: int | None = None
    evidence_requirements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("task_id", "capability", "agent_id", "authorization_scope"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "dependencies", _refs(self.dependencies))
        object.__setattr__(self, "input_refs", _refs(self.input_refs))
        object.__setattr__(self, "evidence_requirements", _refs(self.evidence_requirements))
        if self.retry_limit < 0:
            raise ValueError("retry_limit cannot be negative")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class SwarmTaskGraph:
    mission_id: str
    tasks: tuple[SwarmTask, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _require_text(self.mission_id, "mission_id"))
        if not self.tasks:
            raise ValueError("task graph requires at least one task")
        ids = tuple(task.task_id for task in self.tasks)
        if len(set(ids)) != len(ids):
            raise ValueError("task_id values must be unique")
        known = set(ids)
        for task in self.tasks:
            missing = set(task.dependencies) - known
            if missing:
                raise ValueError(f"unknown task dependencies for {task.task_id}: {sorted(missing)}")
            if task.task_id in task.dependencies:
                raise ValueError("task cannot depend on itself")
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        dependencies = {task.task_id: set(task.dependencies) for task in self.tasks}
        remaining = set(dependencies)
        resolved: set[str] = set()
        while remaining:
            ready = {task_id for task_id in remaining if dependencies[task_id] <= resolved}
            if not ready:
                raise ValueError("task graph contains a dependency cycle")
            resolved.update(ready)
            remaining.difference_update(ready)

    def ready_task_ids(self, completed_task_ids: Iterable[str]) -> tuple[str, ...]:
        completed = set(completed_task_ids)
        return tuple(
            task.task_id
            for task in self.tasks
            if task.status in {"PENDING", "READY", "WAITING_DEPENDENCY"}
            and set(task.dependencies) <= completed
            and task.task_id not in completed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "tasks": [asdict(task) for task in self.tasks],
        }


@dataclass(frozen=True)
class CapabilityCoverageEntry:
    capability: str
    agent: str | None
    selected: bool
    invoked: bool
    live: bool
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    consumed_by: tuple[str, ...]
    returned_to_harness: bool
    status: CoverageStatus


@dataclass(frozen=True)
class CapabilityCoverageMatrix:
    mission_id: str
    entries: tuple[CapabilityCoverageEntry, ...]

    @classmethod
    def derive(
        cls,
        *,
        mission_id: str,
        capability_ids: Iterable[str],
        receipts: Iterable[AgentInvocationReceipt],
        structurally_proven: Iterable[str] = (),
        blocked: Iterable[str] = (),
        external_blocked: Iterable[str] = (),
        consumers: dict[str, Iterable[str]] | None = None,
    ) -> "CapabilityCoverageMatrix":
        mission_id = _require_text(mission_id, "mission_id")
        receipt_list = tuple(receipts)
        structural = set(structurally_proven)
        blocked_set = set(blocked)
        external = set(external_blocked)
        consumer_map = consumers or {}
        entries: list[CapabilityCoverageEntry] = []

        for capability in dict.fromkeys(capability_ids):
            matching = tuple(item for item in receipt_list if item.capability == capability)
            selected = bool(matching)
            invoked = any(item.status not in {"PENDING", "READY"} for item in matching)
            live = any(item.proven_live for item in matching)
            returned = any(item.returned_to_harness for item in matching)
            if live:
                status: CoverageStatus = "PROVEN_LIVE"
            elif any(item.proven_structural for item in matching) or capability in structural:
                status = "PROVEN_STRUCTURAL"
            elif capability in external:
                status = "DEGRADED_EXTERNAL_BLOCKER"
            elif capability in blocked_set:
                status = "BLOCKED"
            elif matching and any(item.status in _TERMINAL_FAILURE for item in matching):
                status = "PARTIAL"
            elif not matching:
                status = "AVAILABLE_UNEXERCISED"
            else:
                status = "UNPROVEN"

            entries.append(
                CapabilityCoverageEntry(
                    capability=capability,
                    agent=matching[-1].agent_id if matching else None,
                    selected=selected,
                    invoked=invoked,
                    live=live,
                    input_refs=_refs(ref for item in matching for ref in item.input_refs),
                    output_refs=_refs(ref for item in matching for ref in item.output_refs),
                    evidence_refs=_refs(ref for item in matching for ref in item.evidence_refs),
                    consumed_by=_refs(consumer_map.get(capability, ())),
                    returned_to_harness=returned,
                    status=status,
                )
            )
        return cls(mission_id=mission_id, entries=tuple(entries))

    @property
    def all_proven_live(self) -> bool:
        return bool(self.entries) and all(item.status == "PROVEN_LIVE" for item in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "all_proven_live": self.all_proven_live,
            "entries": [asdict(item) for item in self.entries],
        }


@dataclass(frozen=True)
class SwarmMissionProof:
    mission_id: str
    goal_id: str
    harness_decision_id: str
    authorization_id: str
    plan_ref: str
    task_graph_ref: str
    receipts: tuple[AgentInvocationReceipt, ...]
    qa_result_ref: str | None = None
    qa_passed: bool = False
    render_job_id: int | None = None
    video_id: int | None = None
    artifact_ref: str | None = None
    mp4_sha256: str | None = None
    telegram_ingress_ref: str | None = None
    telegram_delivery_ref: str | None = None
    knowledge_return_ref: str | None = None
    publication_gate_ref: str | None = None
    publication_attempted: bool = False
    job18_state_before: str | None = None
    job18_state_after: str | None = None
    job20_reused_as_final: bool = False
    review_state: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "mission_id",
            "goal_id",
            "harness_decision_id",
            "authorization_id",
            "plan_ref",
            "task_graph_ref",
        ):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        if any(receipt.mission_id != self.mission_id for receipt in self.receipts):
            raise ValueError("all receipts must belong to the mission")
        if self.mp4_sha256 is not None:
            digest = self.mp4_sha256.lower().strip()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("mp4_sha256 must be a 64-character hexadecimal SHA256")
            object.__setattr__(self, "mp4_sha256", digest)

    @property
    def job18_unchanged(self) -> bool:
        return bool(
            self.job18_state_before is not None
            and self.job18_state_after is not None
            and self.job18_state_before == self.job18_state_after
        )

    @property
    def publication_gate_preserved(self) -> bool:
        return bool(self.publication_gate_ref and not self.publication_attempted)

    @property
    def live_invocation_proven(self) -> bool:
        return any(receipt.proven_live for receipt in self.receipts)

    @property
    def telegram_roundtrip_proven(self) -> bool:
        return bool(self.telegram_ingress_ref and self.telegram_delivery_ref)

    @property
    def render_proven(self) -> bool:
        return bool(
            self.render_job_id is not None
            and self.video_id is not None
            and self.artifact_ref
            and self.mp4_sha256
            and self.qa_passed
            and self.qa_result_ref
        )

    @property
    def end_to_end_synergy_passed(self) -> bool:
        return bool(
            self.live_invocation_proven
            and self.telegram_roundtrip_proven
            and self.render_proven
            and self.knowledge_return_ref
            and self.publication_gate_preserved
            and self.job18_unchanged
            and not self.job20_reused_as_final
            and self.review_state == "READY_FOR_HUMAN_REVIEW"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "goal_id": self.goal_id,
            "harness_decision_id": self.harness_decision_id,
            "authorization_id": self.authorization_id,
            "plan_ref": self.plan_ref,
            "task_graph_ref": self.task_graph_ref,
            "agent_invocation_receipts": [receipt.to_dict() for receipt in self.receipts],
            "qa_result_ref": self.qa_result_ref,
            "qa_passed": self.qa_passed,
            "render_job_id": self.render_job_id,
            "video_id": self.video_id,
            "artifact_ref": self.artifact_ref,
            "mp4_sha256": self.mp4_sha256,
            "telegram_ingress_ref": self.telegram_ingress_ref,
            "telegram_delivery_ref": self.telegram_delivery_ref,
            "knowledge_return_ref": self.knowledge_return_ref,
            "publication_gate_ref": self.publication_gate_ref,
            "publication_attempted": self.publication_attempted,
            "job18_state_before": self.job18_state_before,
            "job18_state_after": self.job18_state_after,
            "job18_unchanged": self.job18_unchanged,
            "job20_reused_as_final": self.job20_reused_as_final,
            "review_state": self.review_state,
            "live_invocation_proven": self.live_invocation_proven,
            "telegram_roundtrip_proven": self.telegram_roundtrip_proven,
            "render_proven": self.render_proven,
            "publication_gate_preserved": self.publication_gate_preserved,
            "end_to_end_synergy_passed": self.end_to_end_synergy_passed,
            "metadata": dict(self.metadata),
        }
