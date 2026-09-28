import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


_MANIFEST_RELATIVE_PATH = Path("config") / "agent_skill_pack_v1.json"
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_NONE_AUTHORITY = "NONE"


@dataclass(frozen=True)
class AgentSkillSource:
    repository: str
    commit: str
    path: str
    license: str
    upstream_repository: str | None = None
    upstream_commit: str | None = None


@dataclass(frozen=True)
class AgentSkillEntry:
    skill_id: str
    kind: str
    source: AgentSkillSource
    provider_id: str | None
    local_path: str | None
    content_digest: str | None
    invocation_policy: str
    authority: str
    routing_authority: str
    policy_authority: str
    publication_authority: str
    memory_write: str
    side_effect_class: str
    direct_external_side_effects: bool
    direct_repository_mutation: bool


@dataclass(frozen=True)
class AgentSkillPack:
    schema_version: int
    control_plane: str
    superpowers_bootstrap_global: bool
    skills: tuple[AgentSkillEntry, ...]


@dataclass(frozen=True)
class SkillPackVerification:
    status: str
    requested_skill_ids: tuple[str, ...]
    materialized_skill_ids: tuple[str, ...]
    pending_skill_ids: tuple[str, ...]
    authority: str
    bootstrap_global: bool


def _require_full_sha(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not _FULL_SHA.fullmatch(text):
        raise ValueError(f"{field} must be a pinned 40-character lowercase git SHA")
    return text


def _require_none_authority(value: object, *, field: str) -> str:
    text = str(value or "").strip().upper()
    if text != _NONE_AUTHORITY:
        raise ValueError(f"{field} must remain NONE")
    return text


def _parse_source(raw: dict, *, skill_id: str) -> AgentSkillSource:
    commit = _require_full_sha(raw.get("commit"), field=f"{skill_id}.source.commit")
    upstream_commit = raw.get("upstream_commit")
    if upstream_commit is not None:
        upstream_commit = _require_full_sha(
            upstream_commit,
            field=f"{skill_id}.source.upstream_commit",
        )
    repository = str(raw.get("repository") or "").strip()
    source_path = str(raw.get("path") or "").strip()
    license_name = str(raw.get("license") or "").strip()
    if not repository or not source_path or not license_name:
        raise ValueError(f"{skill_id}.source is incomplete")
    return AgentSkillSource(
        repository=repository,
        commit=commit,
        path=source_path,
        license=license_name,
        upstream_repository=(
            str(raw.get("upstream_repository")).strip()
            if raw.get("upstream_repository") is not None
            else None
        ),
        upstream_commit=upstream_commit,
    )


def _parse_entry(raw: dict) -> AgentSkillEntry:
    skill_id = str(raw.get("skill_id") or "").strip()
    if not skill_id:
        raise ValueError("skill_id is required")
    return AgentSkillEntry(
        skill_id=skill_id,
        kind=str(raw.get("kind") or "SKILL").strip(),
        source=_parse_source(dict(raw.get("source") or {}), skill_id=skill_id),
        provider_id=(
            str(raw.get("provider_id")).strip()
            if raw.get("provider_id") is not None
            else None
        ),
        local_path=(
            str(raw.get("local_path")).strip()
            if raw.get("local_path") is not None
            else None
        ),
        content_digest=(
            str(raw.get("content_digest")).strip()
            if raw.get("content_digest") is not None
            else None
        ),
        invocation_policy=str(raw.get("invocation_policy") or "").strip(),
        authority=_require_none_authority(
            raw.get("authority"),
            field=f"{skill_id}.authority",
        ),
        routing_authority=_require_none_authority(
            raw.get("routing_authority"),
            field=f"{skill_id}.routing_authority",
        ),
        policy_authority=_require_none_authority(
            raw.get("policy_authority"),
            field=f"{skill_id}.policy_authority",
        ),
        publication_authority=_require_none_authority(
            raw.get("publication_authority"),
            field=f"{skill_id}.publication_authority",
        ),
        memory_write=str(raw.get("memory_write") or "").strip().upper(),
        side_effect_class=str(raw.get("side_effect_class") or "").strip().upper(),
        direct_external_side_effects=bool(raw.get("direct_external_side_effects")),
        direct_repository_mutation=bool(raw.get("direct_repository_mutation")),
    )


def load_agent_skill_pack(root: Path) -> AgentSkillPack:
    root = Path(root)
    raw = json.loads((root / _MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    schema_version = raw.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"unsupported agent skill pack schema_version={schema_version!r}")
    bootstrap = raw.get("superpowers_bootstrap_global")
    if bootstrap is not False:
        raise ValueError("superpowers_bootstrap_global must remain false")
    control_plane = str(raw.get("control_plane") or "").strip().upper()
    if control_plane != "DEEPSEEK_HARNESS":
        raise ValueError("control_plane must remain DEEPSEEK_HARNESS")

    skills = tuple(_parse_entry(dict(item)) for item in raw.get("skills") or ())
    ids = [entry.skill_id for entry in skills]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate exposed skill_id in agent skill pack")
    if not skills:
        raise ValueError("agent skill pack must not be empty")

    for entry in skills:
        if entry.direct_external_side_effects:
            raise ValueError(
                f"{entry.skill_id}.direct_external_side_effects must remain false"
            )
        if entry.direct_repository_mutation:
            raise ValueError(
                f"{entry.skill_id}.direct_repository_mutation must remain false"
            )

    return AgentSkillPack(
        schema_version=1,
        control_plane=control_plane,
        superpowers_bootstrap_global=False,
        skills=skills,
    )



def skill_tree_digest(path: Path) -> str:
    path = Path(path)
    if not path.is_dir():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    files = sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix(),
    )
    if not files:
        raise ValueError(f"skill bundle is empty: {path}")
    for item in files:
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def verify_agent_skill_pack(root: Path) -> SkillPackVerification:
    root = Path(root)
    pack = load_agent_skill_pack(root)
    materialized: list[str] = []
    pending: list[str] = []
    for entry in pack.skills:
        if not entry.local_path:
            continue
        local_path = root / entry.local_path
        if not local_path.is_dir():
            pending.append(entry.skill_id)
            continue
        if not entry.content_digest:
            raise ValueError(
                f"missing content digest for materialized skill {entry.skill_id}"
            )
        actual_digest = skill_tree_digest(local_path)
        if actual_digest != entry.content_digest:
            raise ValueError(
                "digest mismatch for "
                f"{entry.skill_id}: expected={entry.content_digest} "
                f"actual={actual_digest}"
            )
        materialized.append(entry.skill_id)

    return SkillPackVerification(
        status="PENDING_MATERIALIZATION" if pending else "PASS",
        requested_skill_ids=tuple(entry.skill_id for entry in pack.skills),
        materialized_skill_ids=tuple(materialized),
        pending_skill_ids=tuple(pending),
        authority="DEEPSEEK_HARNESS",
        bootstrap_global=pack.superpowers_bootstrap_global,
    )
