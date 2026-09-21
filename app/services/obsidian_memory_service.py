from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from app.database import harness_learning_repository as learning_repository
from app.database import continuous_operation_repository as continuous_repository
from app.database.memory_claim_repository import get_memory_claim
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_learning_service import HarnessEpisode, persist_episode
from app.services.memory_plane_service import record_canonical_human_decision


OBSIDIAN_INBOX_CAPABILITY_ID = "memory.obsidian.inbox.ingest"
OBSIDIAN_INBOX_EXECUTOR_BINDING = (
    "app.services.obsidian_memory_service.execute_obsidian_inbox_capability"
)
OBSIDIAN_EXPORT_CAPABILITY_ID = "memory.obsidian.export"
OBSIDIAN_EXPORT_EXECUTOR_BINDING = (
    "app.services.obsidian_memory_service.execute_obsidian_export_capability"
)

MAX_NOTE_BYTES = 64 * 1024
MAX_EXPORT_FILE_BYTES = 96 * 1024

_FRONTMATTER_LINE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _yaml_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, dict, int, float)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return json.dumps(str(value), ensure_ascii=False)


def _markdown(frontmatter: Mapping[str, Any], title: str, body: str) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {_yaml_value(value)}")
    lines.extend(["---", "", f"# {title}", "", body.strip(), ""])
    text = "\n".join(lines)
    if len(text.encode("utf-8")) > MAX_EXPORT_FILE_BYTES:
        raise ValueError("Obsidian projection file exceeds bounded size")
    return text


def _write_markdown(root: Path, relative: str, text: str) -> str:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return relative


def parse_human_note(note_text: str) -> dict[str, Any]:
    raw = str(note_text or "")
    if not raw.strip():
        raise ValueError("Obsidian note is empty")
    if len(raw.encode("utf-8")) > MAX_NOTE_BYTES:
        raise ValueError("Obsidian note exceeds lightweight inbox limit")
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Obsidian human note requires frontmatter")
    try:
        end = next(
            index for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise ValueError("Obsidian frontmatter is not closed") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        match = _FRONTMATTER_LINE.match(line)
        if match is None:
            raise ValueError("Obsidian frontmatter must be simple key:value metadata")
        metadata[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    if metadata.get("type", "").casefold() != "human_note":
        raise ValueError("Obsidian Inbox accepts type: human_note only")
    target = metadata.get("target", "").strip()
    if not target:
        raise ValueError("Obsidian human note requires target")
    body = "\n".join(lines[end + 1:]).strip()
    if not body:
        raise ValueError("Obsidian human note body is empty")
    return {
        "type": "human_note",
        "target": target,
        "body": body,
        "frontmatter": metadata,
    }


def _find_candidate_for_episode(episode_id: str) -> dict[str, Any] | None:
    for memory in learning_repository.list_memories(
        status="CANDIDATE",
        limit=200,
    ):
        if episode_id in (memory.get("source_episode_ids") or ()):
            return memory
    return None


def execute_obsidian_inbox_capability(
    *,
    authorization,
    routing_decision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{OBSIDIAN_INBOX_CAPABILITY_ID}",
    )
    if routing_decision.selected_capability_id != OBSIDIAN_INBOX_CAPABILITY_ID:
        raise PermissionError("Obsidian inbox routing capability mismatch")
    if routing_decision.selected_executor_binding != OBSIDIAN_INBOX_EXECUTOR_BINDING:
        raise PermissionError("Obsidian inbox executor escaped Registry binding")

    parsed = parse_human_note(str(payload.get("note_text") or ""))
    source_ref = str(payload.get("source_ref") or "").strip()
    goal_id = str(payload.get("goal_id") or "").strip()
    if not source_ref or not goal_id:
        raise ValueError("Obsidian inbox ingestion requires source_ref and goal_id")
    evidence_ref = (
        f"obsidian-inbox:{source_ref}:sha256:"
        + sha256(str(payload["note_text"]).encode("utf-8")).hexdigest()
    )
    decision = record_canonical_human_decision(
        decision_type="USER_NOTE",
        source_surface="obsidian",
        source_ref=source_ref,
        content=parsed["body"],
        evidence_refs=(evidence_ref,),
        goal_id=goal_id,
        task_id=str(payload.get("task_id") or "human-review"),
        artifact_ref=str(payload.get("artifact_ref") or "") or None,
        metadata={
            "target": parsed["target"],
            "frontmatter": parsed["frontmatter"],
            "ingress_capability": OBSIDIAN_INBOX_CAPABILITY_ID,
        },
    )

    now = _utcnow()
    identity = {
        "source_ref": source_ref,
        "goal_id": goal_id,
        "decision_id": decision["decision_id"],
    }
    episode_id = _stable_id("episode", identity)
    episode = HarnessEpisode(
        episode_id=episode_id,
        goal_id=goal_id,
        decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        task_id="obsidian-inbox-ingest",
        agent_id="obsidian-inbox-ingress",
        capability_id=OBSIDIAN_INBOX_CAPABILITY_ID,
        domain="human-memory",
        task_class="obsidian-human-note",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status="COMPLETED",
        actual_outcome={
            "observed": True,
            "note_type": "USER_NOTE",
            "target": parsed["target"],
            "canonical_human_decision_id": decision["decision_id"],
        },
        outcome_evidence=(evidence_ref,),
        input_refs=(source_ref,),
        output_refs=(f"human-decision:{decision['decision_id']}",),
        evidence_refs=(evidence_ref,),
        human_intervention=True,
        qa_results={"frontmatter": "PASS", "bounded_note": "PASS"},
        cost=0.0,
        latency_seconds=0.0,
        artifact_refs=tuple(
            ref for ref in (payload.get("artifact_ref"),) if ref
        ),
        lineage={
            "source_surface": "obsidian",
            "canonical_memory_plane": "HARNESS_LEARNING_PLANE",
            "authorization_id": auth.authorization_id,
            "routing_id": routing_decision.routing_id,
            "memory_candidate_gate": "REQUIRED",
        },
    )
    persisted = persist_episode(episode)
    candidate = _find_candidate_for_episode(episode_id)
    consume_harness_authorization(auth)
    if candidate is None:
        raise RuntimeError("Obsidian note did not produce a MemoryCandidate")
    return {
        "status": "INGESTED",
        "authority": auth.authority,
        "note_type": "USER_NOTE",
        "target": parsed["target"],
        "canonical_human_decision": decision,
        "episode_id": persisted["episode_id"],
        "memory_candidate": candidate,
        "OBSIDIAN_NOTE_INGESTED": "PASS",
        "MEMORY_CANDIDATE_CREATED": "PASS",
        "CANONICAL_AUTO_PROMOTION": "NO",
        "HARNESS_EVALUATION_REQUIRED": "PASS",
        "OBSIDIAN_CANONICAL_MEMORY": "NO",
        "TERMUX_HEAVY_PROCESSING": "NO",
    }


def _frontmatter_for_memory(memory: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(memory.get("metadata") or {})
    return {
        "memory_id": memory.get("memory_id"),
        "episode_id": (
            (memory.get("source_episode_ids") or [None])[0]
            if memory.get("source_episode_ids") else None
        ),
        "goal_id": metadata.get("goal_id"),
        "task_id": metadata.get("task_id"),
        "capability_id": memory.get("capability_id"),
        "agent_id": memory.get("agent_id"),
        "status": memory.get("status"),
        "evidence_refs": list(memory.get("evidence_refs") or ()),
        "created_at": memory.get("created_at"),
        "supersedes": metadata.get("supersedes_memory_id"),
    }


def export_obsidian_memory_projection(
    *,
    output_root: str | Path,
    system_state: Mapping[str, Any],
    project_goals: Mapping[str, str],
) -> dict[str, Any]:
    root = Path(output_root)
    absolute = str(root.expanduser().absolute())
    if "/storage/" in absolute or "/Documents/Obsidian" in absolute:
        raise PermissionError("cloud exporter must not write the Android vault directly")
    root.mkdir(parents=True, exist_ok=True)

    files: list[str] = []
    now = _utcnow()
    evidence_refs = list(system_state.get("evidence_refs") or ())
    files.append(_write_markdown(
        root,
        "00-System/Current-State.md",
        _markdown(
            {
                "status": system_state.get("status", "OBSERVED"),
                "evidence_refs": evidence_refs,
                "created_at": now,
                "authority": "DEEPSEEK_HARNESS",
                "canonical_memory": "BR_SQLITE",
            },
            "Current System State",
            "\n".join([
                f"HEAD: {system_state.get('head') or 'unknown'}",
                "Canonical memory: Harness/Learning Plane SQLite.",
                "Obsidian role: Human Memory Workspace / Published Memory View.",
                "Obsidian is not an authority, executor, Knowledge Brain or Learning Plane.",
                f"OpenCode: {system_state.get('opencode_status') or 'unknown'}",
                f"New voice synthesis: {system_state.get('new_voice_synthesis', 'NO')}",
                f"Full render: {system_state.get('full_render', 'NO')}",
                f"YouTube upload: {system_state.get('youtube_upload', 'NO')}",
                f"YouTube publication: {system_state.get('youtube_publication', 'NO')}",
            ]),
        ),
    ))

    decisions = learning_repository.list_canonical_human_decisions(limit=100)
    episodes = learning_repository.list_episodes(limit=200)
    for project_name, goal_id in project_goals.items():
        slug = str(project_name).upper().replace("_", "-")
        project_decisions = [item for item in decisions if item.get("goal_id") == goal_id]
        latest_decision = project_decisions[0] if project_decisions else None
        if latest_decision:
            files.append(_write_markdown(
                root,
                f"10-Human-Decisions/{slug}.md",
                _markdown(
                    {
                        "memory_id": None,
                        "episode_id": None,
                        "goal_id": goal_id,
                        "task_id": latest_decision.get("task_id"),
                        "capability_id": latest_decision.get("capability_id"),
                        "agent_id": latest_decision.get("agent_id"),
                        "status": latest_decision.get("decision_type"),
                        "evidence_refs": latest_decision.get("evidence_refs") or [],
                        "created_at": latest_decision.get("created_at"),
                        "supersedes": None,
                        "decision_id": latest_decision.get("decision_id"),
                    },
                    f"{slug} Human Decisions",
                    "\n\n".join(
                        f"- **{item.get('decision_type')}** — {item.get('content')}"
                        for item in project_decisions[:12]
                    ),
                ),
            ))

        project_episodes = [item for item in episodes if item.get("goal_id") == goal_id]
        latest_episode = project_episodes[0] if project_episodes else None
        refs = []
        for item in project_episodes[:12]:
            refs.extend(item.get("artifact_refs") or ())
            refs.extend(item.get("output_refs") or ())
        files.append(_write_markdown(
            root,
            f"50-Projects/{slug}/Current-State.md",
            _markdown(
                {
                    "goal_id": goal_id,
                    "episode_id": latest_episode.get("episode_id") if latest_episode else None,
                    "task_id": latest_episode.get("task_id") if latest_episode else None,
                    "capability_id": latest_episode.get("capability_id") if latest_episode else None,
                    "agent_id": latest_episode.get("agent_id") if latest_episode else None,
                    "status": latest_episode.get("status") if latest_episode else "NO_EPISODE",
                    "evidence_refs": (
                        latest_episode.get("evidence_refs") if latest_episode else []
                    ),
                    "created_at": now,
                    "supersedes": None,
                },
                f"{slug} Current State",
                "\n".join([
                    f"Goal: {goal_id}",
                    f"Latest task: {(latest_episode or {}).get('task_id') or 'none'}",
                    f"Latest status: {(latest_episode or {}).get('status') or 'none'}",
                    "Artifact lineage:",
                    *[f"- {ref}" for ref in list(dict.fromkeys(refs))[:30]],
                ]),
            ),
        ))

    memories: list[dict[str, Any]] = []
    for status in ("ACTIVE", "CANDIDATE", "SUPERSEDED"):
        memories.extend(learning_repository.list_memories(status=status, limit=100))

    for memory in memories:
        if memory.get("memory_type") == "FAILURE":
            relative = f"20-Learning/Failures/{memory['memory_id']}.md"
            title = f"Failure Memory — {memory.get('failure_pattern') or memory['memory_id']}"
        elif memory.get("status") == "CANDIDATE":
            relative = f"20-Learning/Improvements/{memory['memory_id']}.md"
            title = f"Memory Candidate — {memory['memory_id']}"
        else:
            continue
        files.append(_write_markdown(
            root,
            relative,
            _markdown(
                _frontmatter_for_memory(memory),
                title,
                "\n".join([
                    str(memory.get("claim") or ""),
                    "",
                    f"Memory class: {(memory.get('metadata') or {}).get('memory_class')}",
                    f"Failure pattern: {memory.get('failure_pattern') or 'n/a'}",
                    f"Confidence: {memory.get('confidence')}",
                    f"Evaluation required: {(memory.get('metadata') or {}).get('evaluation_required', False)}",
                ]),
            ),
        ))

    hermes_competence = [
        item
        for item in learning_repository.list_competence(limit=100)
        if "hermes" in str(item.get("task_class") or "").casefold()
        or "hermes" in str(item.get("agent_id") or "").casefold()
    ]
    files.append(_write_markdown(
        root,
        "30-Agents/Hermes/Competence.md",
        _markdown(
            {
                "status": "OBSERVED",
                "evidence_refs": list(dict.fromkeys(
                    ref
                    for item in hermes_competence
                    for ref in (item.get("evidence_refs") or ())
                ))[:30],
                "created_at": now,
                "agent_id": "hermes",
                "supersedes": None,
            },
            "Hermes Competence",
            "\n\n".join(
                (
                    f"## {item.get('capability_id')} / {item.get('task_class')}\n"
                    f"Cases: {item.get('tested_cases')} | "
                    f"Success: {item.get('success_count')} | "
                    f"Failures: {item.get('failure_count')} | "
                    f"Status: {item.get('status')}"
                )
                for item in hermes_competence[:20]
            ) or "No persisted Hermes competence records.",
        ),
    ))

    for episode in episodes[:20]:
        files.append(_write_markdown(
            root,
            f"90-Runs/HarnessEpisodes/{episode['episode_id']}.md",
            _markdown(
                {
                    "episode_id": episode.get("episode_id"),
                    "goal_id": episode.get("goal_id"),
                    "task_id": episode.get("task_id"),
                    "capability_id": episode.get("capability_id"),
                    "agent_id": episode.get("agent_id"),
                    "status": episode.get("status"),
                    "evidence_refs": episode.get("evidence_refs") or [],
                    "created_at": episode.get("finished_at"),
                    "supersedes": None,
                },
                f"HarnessEpisode — {episode['episode_id']}",
                "\n".join([
                    f"Execution: {episode.get('execution_id')}",
                    f"Run: {episode.get('run_ref') or 'n/a'}",
                    f"Task class: {episode.get('task_class')}",
                    f"Retries: {episode.get('retry_count')}",
                    f"Human intervention: {bool(episode.get('human_intervention'))}",
                    "Artifacts:",
                    *[f"- {ref}" for ref in (episode.get("artifact_refs") or ())],
                ]),
            ),
        ))

    manifest = {
        "schema": "obsidian-memory-export/v1",
        "authority": "DEEPSEEK_HARNESS",
        "canonical_source": "BR SQLite Learning Plane",
        "obsidian_role": "PROJECTION_ONLY",
        "generated_at": now,
        "files": sorted(files),
        "file_count": len(files),
        "OBSIDIAN_CANONICAL_MEMORY": "NO",
        "TERMUX_HEAVY_PROCESSING": "NO",
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def execute_obsidian_export_capability(
    *,
    authorization,
    routing_decision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{OBSIDIAN_EXPORT_CAPABILITY_ID}",
    )
    if routing_decision.selected_capability_id != OBSIDIAN_EXPORT_CAPABILITY_ID:
        raise PermissionError("Obsidian export routing capability mismatch")
    if routing_decision.selected_executor_binding != OBSIDIAN_EXPORT_EXECUTOR_BINDING:
        raise PermissionError("Obsidian export executor escaped Registry binding")
    manifest = export_obsidian_memory_projection(
        output_root=payload["output_root"],
        system_state=dict(payload.get("system_state") or {}),
        project_goals=dict(payload.get("project_goals") or {}),
    )
    consume_harness_authorization(auth)
    return {
        "status": "EXPORTED",
        "authority": auth.authority,
        "manifest": manifest,
        "OBSIDIAN_EXPORT": "PASS",
        "OBSIDIAN_CANONICAL_MEMORY": "NO",
        "TERMUX_HEAVY_PROCESSING": "NO",
    }
