from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import importlib.util
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping, Sequence

from app.services.task_execution_foundation_service import SkillSelectionReceipt


@dataclass(frozen=True)
class SkillExecutionBinding:
    skill_id: str
    version: str
    source: str
    source_commit: str
    content_digest: str
    instruction_hash: str
    task_id: str
    agent_session_id: str
    why_selected: str
    materialized_path: str
    authority: str = "NONE"
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    schema: str = "SkillExecutionBinding/v1"

    def __post_init__(self) -> None:
        if self.authority != "NONE":
            raise PermissionError("Skill authority must remain NONE")
        if len(self.source_commit) != 40:
            raise ValueError("Skill source commit must be a full git SHA")
        if not self.content_digest.startswith("sha256:"):
            raise ValueError("Skill content digest must be sha256")
        if len(self.instruction_hash) != 64:
            raise ValueError("Skill instruction hash must be sha256 hex")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillMaterializationPlan:
    task_id: str
    session_id: str
    selected_skill_ids: tuple[str, ...]
    bindings: tuple[SkillExecutionBinding, ...]
    capability_directories: tuple[str, ...]
    catalog_size: int
    selection_receipts: tuple[SkillSelectionReceipt, ...] = ()
    schema: str = "SkillMaterializationPlan/v1"

    @property
    def progressively_loaded(self) -> bool:
        return len(self.selected_skill_ids) < self.catalog_size

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "progressively_loaded": self.progressively_loaded,
        }


def _load_pack_module(repo_root: Path):
    loader = repo_root / "scripts" / "agent-tooling" / "agent_skill_pack.py"
    spec = importlib.util.spec_from_file_location("br_block_a_skill_pack", loader)
    if spec is None or spec.loader is None:
        raise RuntimeError("agent skill pack loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _instruction_hash(skill_dir: Path) -> str:
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(path)
    return sha256(path.read_bytes()).hexdigest()


def select_minimum_skills(
    *,
    repo_root: Path,
    required_skill_ids: Sequence[str],
    allowed_skill_ids: Sequence[str],
) -> tuple[Any, ...]:
    module = _load_pack_module(Path(repo_root))
    pack = module.load_agent_skill_pack(Path(repo_root))
    by_id = {entry.skill_id: entry for entry in pack.skills}
    requested = tuple(dict.fromkeys(str(x).strip() for x in required_skill_ids if str(x).strip()))
    allowed = set(str(x).strip() for x in allowed_skill_ids if str(x).strip())
    if not set(requested).issubset(allowed):
        raise PermissionError("requested Skill escapes Harness/Task authorization")
    selected = []
    for skill_id in requested:
        entry = by_id.get(skill_id)
        if entry is None or entry.kind != "SKILL":
            raise LookupError(f"eligible Skill not found: {skill_id}")
        if (
            entry.authority != "NONE"
            or entry.routing_authority != "NONE"
            or entry.policy_authority != "NONE"
            or entry.publication_authority != "NONE"
        ):
            raise PermissionError(f"Skill {skill_id} attempts to expand authority")
        if entry.direct_external_side_effects or entry.direct_repository_mutation:
            raise PermissionError(f"Skill {skill_id} carries direct side-effect authority")
        if not entry.local_path or not entry.content_digest:
            raise RuntimeError(f"Skill {skill_id} is not materialized")
        local = Path(repo_root) / entry.local_path
        actual = module.skill_tree_digest(local)
        if actual != entry.content_digest:
            raise RuntimeError(f"Skill provenance drift: {skill_id}")
        selected.append(entry)
    return tuple(selected)


def materialize_selected_skills(
    *,
    repo_root: Path,
    capability_root: Path,
    task_id: str,
    session_id: str,
    selections: Mapping[str, str],
    allowed_skill_ids: Sequence[str],
    required_capabilities: Mapping[str, str] | None = None,
) -> SkillMaterializationPlan:
    repo_root = Path(repo_root).resolve()
    capability_root = Path(capability_root).resolve()
    if not str(capability_root).startswith("/"):
        raise ValueError("capability_root must be absolute")
    required = tuple(selections)
    selected = select_minimum_skills(
        repo_root=repo_root,
        required_skill_ids=required,
        allowed_skill_ids=allowed_skill_ids,
    )
    module = _load_pack_module(repo_root)
    pack = module.load_agent_skill_pack(repo_root)
    task_dir = capability_root / "skills"
    task_dir.mkdir(parents=True, exist_ok=True)

    bindings: list[SkillExecutionBinding] = []
    for entry in selected:
        source_dir = (repo_root / entry.local_path).resolve()
        target = task_dir / entry.skill_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_dir, target)
        copied_digest = module.skill_tree_digest(target)
        if copied_digest != entry.content_digest:
            raise RuntimeError(f"materialized Skill digest mismatch: {entry.skill_id}")
        bindings.append(
            SkillExecutionBinding(
                skill_id=entry.skill_id,
                version=entry.source.commit,
                source=f"{entry.source.repository}:{entry.source.path}",
                source_commit=entry.source.commit,
                content_digest=entry.content_digest,
                instruction_hash=_instruction_hash(target),
                task_id=str(task_id),
                agent_session_id=str(session_id),
                why_selected=str(selections[entry.skill_id]),
                materialized_path=str(target),
                authority="NONE",
                evidence_refs=(f"skill-digest:{entry.content_digest}",),
            )
        )

    # Register only the parent that contains the selected Skill directories.
    directories = (str(task_dir),) if bindings else ()
    required_capabilities = dict(required_capabilities or {})
    receipts = tuple(
        SkillSelectionReceipt.create(
            task_id=str(task_id),
            skill_id=binding.skill_id,
            version=binding.version,
            source=binding.source,
            content_digest=binding.content_digest,
            selection_reason=binding.why_selected,
            required_capability=required_capabilities.get(
                binding.skill_id,
                f"skill-procedure:{binding.skill_id}",
            ),
            instruction_priority=40,
        )
        for binding in bindings
    )
    return SkillMaterializationPlan(
        task_id=str(task_id),
        session_id=str(session_id),
        selected_skill_ids=tuple(binding.skill_id for binding in bindings),
        bindings=tuple(bindings),
        capability_directories=directories,
        catalog_size=len(tuple(item for item in pack.skills if item.kind == "SKILL")),
        selection_receipts=receipts,
    )


def build_self_hosted_environment(
    *,
    workspace_directory: str,
    skill_plan: SkillMaterializationPlan,
) -> dict[str, Any]:
    workspace = str(workspace_directory or "").strip()
    if not workspace.startswith("/"):
        raise ValueError("workspace_directory must be absolute")
    directories = tuple(skill_plan.capability_directories)
    if len(directories) > 32:
        raise ValueError("OpenAI capability_directories ceiling exceeded")
    if any(not path.startswith("/") or "/../" in path or path.endswith("/..") for path in directories):
        raise ValueError("capability_directories must be absolute canonical paths")
    return {
        "type": "self_hosted",
        "workspace_directory": workspace,
        "capability_directories": list(directories),
    }




@dataclass(frozen=True)
class SkillInstructionBoundaryDecision:
    task_id: str
    skill_id: str
    status: str
    effective_read_scope: tuple[str, ...]
    effective_write_scope: tuple[str, ...]
    effective_tools: tuple[str, ...]
    rejected_expansions: tuple[str, ...]
    authority: str = "TASK_AUTHORITY_WINS"
    schema: str = "SkillInstructionBoundaryDecision/v1"


def enforce_skill_instruction_priority(
    *,
    task_id: str,
    authorized_read_scope: Sequence[str],
    authorized_write_scope: Sequence[str],
    authorized_tools: Sequence[str],
    requested_read_scope: Sequence[str],
    requested_write_scope: Sequence[str],
    requested_tools: Sequence[str],
    skill_id: str,
) -> SkillInstructionBoundaryDecision:
    read_auth = tuple(dict.fromkeys(str(x) for x in authorized_read_scope if str(x)))
    write_auth = tuple(dict.fromkeys(str(x) for x in authorized_write_scope if str(x)))
    tool_auth = tuple(dict.fromkeys(str(x) for x in authorized_tools if str(x)))
    read_req = tuple(dict.fromkeys(str(x) for x in requested_read_scope if str(x)))
    write_req = tuple(dict.fromkeys(str(x) for x in requested_write_scope if str(x)))
    tool_req = tuple(dict.fromkeys(str(x) for x in requested_tools if str(x)))

    effective_read = tuple(x for x in read_req if x in set(read_auth))
    effective_write = tuple(x for x in write_req if x in set(write_auth))
    effective_tools = tuple(x for x in tool_req if x in set(tool_auth))
    rejected = (
        *(f"read:{x}" for x in read_req if x not in set(read_auth)),
        *(f"write:{x}" for x in write_req if x not in set(write_auth)),
        *(f"tool:{x}" for x in tool_req if x not in set(tool_auth)),
    )
    return SkillInstructionBoundaryDecision(
        task_id=str(task_id),
        skill_id=str(skill_id),
        status="CONFLICT_RECORDED" if rejected else "PASS",
        effective_read_scope=effective_read,
        effective_write_scope=effective_write,
        effective_tools=effective_tools,
        rejected_expansions=tuple(rejected),
    )


def skill_policy_allowed_tools(
    bindings: Iterable[SkillExecutionBinding],
    *,
    default_allowed_tools: Sequence[str],
) -> tuple[str, ...]:
    # Skills are procedural input. They never add tools. This function therefore
    # returns only the pre-authorized tool set and is intentionally monotonic.
    for binding in bindings:
        if binding.authority != "NONE":
            raise PermissionError("Skill attempted authority escalation")
    return tuple(dict.fromkeys(str(x) for x in default_allowed_tools if str(x)))


__all__ = [
    "SkillExecutionBinding",
    "SkillMaterializationPlan",
    "SkillInstructionBoundaryDecision",
    "build_self_hosted_environment",
    "materialize_selected_skills",
    "select_minimum_skills",
    "skill_policy_allowed_tools",
    "enforce_skill_instruction_priority",
]
