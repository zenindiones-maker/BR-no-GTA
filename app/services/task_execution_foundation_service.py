from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence
from pathlib import Path


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _content_sha256(value: Mapping[str, Any]) -> str:
    return sha256(_canonical_bytes(dict(value))).hexdigest()


def _text(value: Any, name: str, *, maximum: int = 4000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return text


def _digest(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    text = _text(value, name, maximum=71)
    raw = text.removeprefix("sha256:")
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw.lower()):
        raise ValueError(f"{name} must be a sha256 digest")
    return text


def _tuple(value: Sequence[Any] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(dict.fromkeys(_text(item, "item", maximum=2000) for item in value))


_COGNITIVE_FIELDS = (
    "decomposability",
    "dependency_density",
    "parallelizable_branch_count",
    "shared_mutable_state",
    "write_set_overlap",
    "context_coupling",
    "uncertainty",
    "evidence_demand",
    "tool_density",
    "reasoning_depth",
    "creativity_demand",
    "mutation_required",
    "reversibility",
    "risk_class",
    "need_for_independence",
    "expected_coordination_overhead",
    "estimated_context_demand",
)


@dataclass(frozen=True)
class TaskCognitiveProfile:
    task_id: str
    task_class: str
    decomposability: Any
    dependency_density: Any
    parallelizable_branch_count: int
    shared_mutable_state: bool
    write_set_overlap: bool
    context_coupling: Any
    uncertainty: Any
    evidence_demand: Any
    tool_density: Any
    reasoning_depth: Any
    creativity_demand: Any
    mutation_required: bool
    reversibility: Any
    risk_class: str
    need_for_independence: bool
    expected_coordination_overhead: Any
    estimated_context_demand: Any
    reasons: dict[str, str]
    evidence_refs: tuple[str, ...]
    content_sha256: str
    schema: str = "TaskCognitiveProfile/v1"

    @property
    def classification_reasons(self) -> dict[str, str]:
        return self.reasons

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["classification_reasons"] = dict(self.reasons)
        return value


def build_task_cognitive_profile(
    *,
    task_id: str,
    task_class: str,
    evidence: Mapping[str, tuple[Any, str]],
    evidence_refs: Sequence[str] = (),
) -> TaskCognitiveProfile:
    missing = [name for name in _COGNITIVE_FIELDS if name not in evidence]
    if missing:
        raise ValueError("classification evidence/reason missing: " + ",".join(missing))
    values: dict[str, Any] = {}
    reasons: dict[str, str] = {}
    for name in _COGNITIVE_FIELDS:
        raw = evidence[name]
        if not isinstance(raw, (tuple, list)) or len(raw) != 2:
            raise ValueError(f"{name} requires (value, evidence/reason)")
        value, reason = raw
        reason_text = str(reason or "").strip()
        if not reason_text:
            raise ValueError(f"{name} requires evidence/reason")
        values[name] = value
        reasons[name] = reason_text

    if isinstance(values["parallelizable_branch_count"], bool):
        raise ValueError("parallelizable_branch_count must be an integer")
    branches = int(values["parallelizable_branch_count"])
    if branches < 0:
        raise ValueError("parallelizable_branch_count must be non-negative")

    base = {
        "task_id": _text(task_id, "task_id", maximum=192),
        "task_class": _text(task_class, "task_class", maximum=192),
        **values,
        "parallelizable_branch_count": branches,
        "shared_mutable_state": bool(values["shared_mutable_state"]),
        "write_set_overlap": bool(values["write_set_overlap"]),
        "mutation_required": bool(values["mutation_required"]),
        "need_for_independence": bool(values["need_for_independence"]),
        "risk_class": _text(values["risk_class"], "risk_class", maximum=64),
        "reasons": reasons,
        "evidence_refs": _tuple(evidence_refs),
        "schema": "TaskCognitiveProfile/v1",
    }
    digest = _content_sha256(base)
    return TaskCognitiveProfile(**{k: v for k, v in base.items() if k != "schema"}, content_sha256=digest)


@dataclass(frozen=True)
class TaskContextManifest:
    task_id: str
    mandatory_context: tuple[str, ...]
    on_demand_context: tuple[str, ...]
    forbidden_context: tuple[str, ...]
    context_bytes: int
    context_items: int
    irrelevant_context_items: int
    retrieval_count: int
    compaction_count: int
    content_sha256: str
    schema: str = "TaskContextManifest/v1"

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        mandatory_context: Sequence[str],
        on_demand_context: Sequence[str],
        forbidden_context: Sequence[str],
        context_bytes: int,
        irrelevant_context_items: int,
        retrieval_count: int,
        compaction_count: int = 0,
    ) -> "TaskContextManifest":
        mandatory = _tuple(mandatory_context)
        on_demand = _tuple(on_demand_context)
        forbidden = _tuple(forbidden_context)
        if set(mandatory) & set(forbidden):
            raise PermissionError("mandatory context intersects forbidden context")
        if set(on_demand) & set(forbidden):
            raise PermissionError("on-demand context intersects forbidden context")
        for name, raw in (
            ("context_bytes", context_bytes),
            ("irrelevant_context_items", irrelevant_context_items),
            ("retrieval_count", retrieval_count),
            ("compaction_count", compaction_count),
        ):
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        base = {
            "task_id": _text(task_id, "task_id", maximum=192),
            "mandatory_context": mandatory,
            "on_demand_context": on_demand,
            "forbidden_context": forbidden,
            "context_bytes": context_bytes,
            "context_items": len(mandatory) + len(on_demand),
            "irrelevant_context_items": irrelevant_context_items,
            "retrieval_count": retrieval_count,
            "compaction_count": compaction_count,
            "schema": "TaskContextManifest/v1",
        }
        return cls(
            **{k: v for k, v in base.items() if k != "schema"},
            content_sha256=_content_sha256(base),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskExecutionBlueprint:
    mission_id: str
    task_id: str
    typed_requirement_digest: str
    atomicity_digest: str
    dependency_refs: tuple[str, ...]
    input_refs: tuple[str, ...]
    output_contract: str
    acceptance_criteria: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    cognitive_profile_digest: str
    topology_assessment_digest: str
    effort_budget_digest: str
    required_capabilities: tuple[str, ...]
    selected_capability: str
    selected_worker: str
    worker_build_version: str
    coalition_plan_digest: str | None
    context_manifest_digest: str
    selected_skill_refs: tuple[str, ...]
    selected_tool_refs: tuple[str, ...]
    environment_lease_ref: str
    read_scope: tuple[str, ...]
    write_scope: tuple[str, ...]
    side_effect_scope: tuple[str, ...]
    retry_semantics: str
    recovery_semantics: str
    review_policy: str
    completion_conditions: tuple[str, ...]
    authorization_ref: str
    plan_hash: str
    repo_revision: str
    runtime_revision: str
    content_sha256: str
    authority: str = "DEEPSEEK_HARNESS"
    schema: str = "TaskExecutionBlueprint/v1"

    def __post_init__(self) -> None:
        if self.authority != "DEEPSEEK_HARNESS":
            raise PermissionError("TaskExecutionBlueprint authority must remain DEEPSEEK_HARNESS")

    @classmethod
    def create(cls, **raw: Any) -> "TaskExecutionBlueprint":
        base = {
            "mission_id": _text(raw["mission_id"], "mission_id", maximum=192),
            "task_id": _text(raw["task_id"], "task_id", maximum=192),
            "typed_requirement_digest": _digest(raw["typed_requirement_digest"], "typed_requirement_digest"),
            "atomicity_digest": _digest(raw["atomicity_digest"], "atomicity_digest"),
            "dependency_refs": _tuple(raw.get("dependency_refs")),
            "input_refs": _tuple(raw.get("input_refs")),
            "output_contract": _text(raw["output_contract"], "output_contract", maximum=192),
            "acceptance_criteria": _tuple(raw.get("acceptance_criteria")),
            "evidence_requirements": _tuple(raw.get("evidence_requirements")),
            "cognitive_profile_digest": _digest(raw["cognitive_profile_digest"], "cognitive_profile_digest"),
            "topology_assessment_digest": _digest(raw["topology_assessment_digest"], "topology_assessment_digest"),
            "effort_budget_digest": _digest(raw["effort_budget_digest"], "effort_budget_digest"),
            "required_capabilities": _tuple(raw.get("required_capabilities")),
            "selected_capability": _text(raw["selected_capability"], "selected_capability", maximum=192),
            "selected_worker": _text(raw["selected_worker"], "selected_worker", maximum=192),
            "worker_build_version": _text(raw["worker_build_version"], "worker_build_version", maximum=192),
            "coalition_plan_digest": _digest(raw.get("coalition_plan_digest"), "coalition_plan_digest", allow_none=True),
            "context_manifest_digest": _digest(raw["context_manifest_digest"], "context_manifest_digest"),
            "selected_skill_refs": _tuple(raw.get("selected_skill_refs")),
            "selected_tool_refs": _tuple(raw.get("selected_tool_refs")),
            "environment_lease_ref": _text(raw["environment_lease_ref"], "environment_lease_ref", maximum=500),
            "read_scope": _tuple(raw.get("read_scope")),
            "write_scope": _tuple(raw.get("write_scope")),
            "side_effect_scope": _tuple(raw.get("side_effect_scope")),
            "retry_semantics": _text(raw["retry_semantics"], "retry_semantics", maximum=500),
            "recovery_semantics": _text(raw["recovery_semantics"], "recovery_semantics", maximum=500),
            "review_policy": _text(raw["review_policy"], "review_policy", maximum=500),
            "completion_conditions": _tuple(raw.get("completion_conditions")),
            "authorization_ref": _text(raw["authorization_ref"], "authorization_ref", maximum=500),
            "plan_hash": _digest(raw["plan_hash"], "plan_hash"),
            "repo_revision": _text(raw["repo_revision"], "repo_revision", maximum=64),
            "runtime_revision": _text(raw["runtime_revision"], "runtime_revision", maximum=192),
            "authority": "DEEPSEEK_HARNESS",
            "schema": "TaskExecutionBlueprint/v1",
        }
        if base["selected_capability"] not in base["required_capabilities"]:
            raise PermissionError("selected capability is not required/authorized")
        if base["write_scope"] and "repository_mutation" not in base["side_effect_scope"]:
            raise PermissionError("write scope requires repository_mutation side effect authorization")
        return cls(
            **{k: v for k, v in base.items() if k not in {"schema", "authority"}},
            content_sha256=_content_sha256(base),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_blueprint_bindings(
    blueprint: TaskExecutionBlueprint,
    **observed: str,
) -> None:
    expected = {
        "typed_requirement_digest": blueprint.typed_requirement_digest,
        "atomicity_digest": blueprint.atomicity_digest,
        "cognitive_profile_digest": blueprint.cognitive_profile_digest,
        "topology_assessment_digest": blueprint.topology_assessment_digest,
        "effort_budget_digest": blueprint.effort_budget_digest,
        "context_manifest_digest": blueprint.context_manifest_digest,
        "plan_hash": blueprint.plan_hash,
        "repo_revision": blueprint.repo_revision,
        "runtime_revision": blueprint.runtime_revision,
    }
    mismatches = [
        key for key, expected_value in expected.items()
        if str(observed.get(key) or "") != str(expected_value)
    ]
    if mismatches:
        raise PermissionError(
            "TaskExecutionBlueprint stale/mismatched bindings: " + ",".join(sorted(mismatches))
        )


@dataclass(frozen=True)
class TaskProgressLedger:
    task_id: str
    blueprint_digest: str
    current_state: str
    completed_milestones: tuple[str, ...]
    remaining_milestones: tuple[str, ...]
    produced_artifact_refs: tuple[str, ...]
    verification_state: str
    last_clean_checkpoint: str
    blocker: str | None
    next_allowed_action: str
    updated_at: str
    content_sha256: str
    schema: str = "TaskProgressLedger/v1"

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        blueprint_digest: str,
        milestones: Sequence[str],
        produced_artifact_refs: Sequence[str],
        last_clean_checkpoint: str,
    ) -> "TaskProgressLedger":
        remaining = _tuple(milestones)
        base = {
            "task_id": _text(task_id, "task_id", maximum=192),
            "blueprint_digest": _digest(blueprint_digest, "blueprint_digest"),
            "current_state": "READY",
            "completed_milestones": (),
            "remaining_milestones": remaining,
            "produced_artifact_refs": _tuple(produced_artifact_refs),
            "verification_state": "PENDING",
            "last_clean_checkpoint": _text(last_clean_checkpoint, "last_clean_checkpoint", maximum=500),
            "blocker": None,
            "next_allowed_action": remaining[0] if remaining else "COMPLETE",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "schema": "TaskProgressLedger/v1",
        }
        return cls(
            **{k: v for k, v in base.items() if k != "schema"},
            content_sha256=_content_sha256(base),
        )

    def complete_milestone(
        self,
        milestone: str,
        *,
        artifact_refs: Sequence[str],
        verification_state: str,
    ) -> "TaskProgressLedger":
        milestone = _text(milestone, "milestone", maximum=192)
        if milestone in self.completed_milestones:
            return self
        if not self.remaining_milestones or milestone != self.remaining_milestones[0]:
            raise PermissionError("milestone is not the next allowed action")
        completed = (*self.completed_milestones, milestone)
        remaining = self.remaining_milestones[1:]
        artifacts = tuple(dict.fromkeys((*self.produced_artifact_refs, *_tuple(artifact_refs))))
        base = {
            "task_id": self.task_id,
            "blueprint_digest": self.blueprint_digest,
            "current_state": "COMPLETED" if not remaining else "IN_PROGRESS",
            "completed_milestones": completed,
            "remaining_milestones": remaining,
            "produced_artifact_refs": artifacts,
            "verification_state": _text(verification_state, "verification_state", maximum=64),
            "last_clean_checkpoint": self.last_clean_checkpoint,
            "blocker": None,
            "next_allowed_action": remaining[0] if remaining else "COMPLETE",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "schema": "TaskProgressLedger/v1",
        }
        return TaskProgressLedger(
            **{k: v for k, v in base.items() if k != "schema"},
            content_sha256=_content_sha256(base),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def persist_task_progress_ledger(
    ledger: TaskProgressLedger,
    path: "Path | str",
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = ledger.to_dict()
    target.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return str(target)


def load_task_progress_ledger(
    path: "Path | str",
    *,
    expected_blueprint_digest: str,
) -> TaskProgressLedger:
    target = Path(path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    if raw.get("schema") != "TaskProgressLedger/v1":
        raise ValueError("TaskProgressLedger schema mismatch")
    if str(raw.get("blueprint_digest") or "") != str(expected_blueprint_digest):
        raise PermissionError("TaskProgressLedger blueprint binding mismatch")
    content_sha = str(raw.get("content_sha256") or "")
    base = dict(raw)
    base.pop("content_sha256", None)
    expected = _content_sha256(base)
    if content_sha != expected:
        raise PermissionError("TaskProgressLedger content hash mismatch")
    return TaskProgressLedger(
        task_id=str(raw["task_id"]),
        blueprint_digest=str(raw["blueprint_digest"]),
        current_state=str(raw["current_state"]),
        completed_milestones=tuple(raw.get("completed_milestones") or ()),
        remaining_milestones=tuple(raw.get("remaining_milestones") or ()),
        produced_artifact_refs=tuple(raw.get("produced_artifact_refs") or ()),
        verification_state=str(raw["verification_state"]),
        last_clean_checkpoint=str(raw["last_clean_checkpoint"]),
        blocker=raw.get("blocker"),
        next_allowed_action=str(raw["next_allowed_action"]),
        updated_at=str(raw["updated_at"]),
        content_sha256=content_sha,
    )


@dataclass(frozen=True)
class SkillSelectionReceipt:
    task_id: str
    skill_id: str
    version: str
    source: str
    content_digest: str
    selection_reason: str
    required_capability: str
    instruction_priority: int
    content_sha256: str
    authority: str = "NONE"
    schema: str = "SkillSelectionReceipt/v1"

    def __post_init__(self) -> None:
        if self.authority != "NONE":
            raise PermissionError("SkillSelectionReceipt authority must remain NONE")

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        skill_id: str,
        version: str,
        source: str,
        content_digest: str,
        selection_reason: str,
        required_capability: str,
        instruction_priority: int,
    ) -> "SkillSelectionReceipt":
        if isinstance(instruction_priority, bool) or not isinstance(instruction_priority, int) or instruction_priority < 0:
            raise ValueError("instruction_priority must be a non-negative integer")
        _digest(content_digest, "content_digest")
        base = {
            "task_id": _text(task_id, "task_id", maximum=192),
            "skill_id": _text(skill_id, "skill_id", maximum=192),
            "version": _text(version, "version", maximum=192),
            "source": _text(source, "source", maximum=1000),
            "content_digest": content_digest,
            "selection_reason": _text(selection_reason, "selection_reason", maximum=2000),
            "required_capability": _text(required_capability, "required_capability", maximum=192),
            "instruction_priority": instruction_priority,
            "authority": "NONE",
            "schema": "SkillSelectionReceipt/v1",
        }
        return cls(
            **{k: v for k, v in base.items() if k not in {"schema", "authority"}},
            content_sha256=_content_sha256(base),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "SkillSelectionReceipt",
    "TaskCognitiveProfile",
    "TaskContextManifest",
    "TaskExecutionBlueprint",
    "TaskProgressLedger",
    "build_task_cognitive_profile",
    "validate_blueprint_bindings",
    "persist_task_progress_ledger",
    "load_task_progress_ledger",
]
