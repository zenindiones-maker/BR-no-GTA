from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any

from app.database import harness_learning_repository as learning_repository
from app.database.memory_claim_evidence_repository import (
    list_memory_claim_evidence_for_claim,
)
from app.database.memory_claim_repository import list_memory_claims
from app.services.memory_plane_service import (
    ARTIFACT_LINEAGE_MEMORY,
    CONVERSATION_MEMORY,
    KNOWLEDGE_MEMORY,
    OPERATIONAL_MEMORY,
)


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{2,}", re.IGNORECASE)


def _tokens(*values: Any) -> set[str]:
    result: set[str] = set()
    for value in values:
        for match in _TOKEN_RE.findall(str(value or "").casefold()):
            result.add(match)
    return result


def _compact_memory(item: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(item.get("metadata") or {})
    return {
        "memory_id": item.get("memory_id"),
        "memory_type": item.get("memory_type"),
        "claim": str(item.get("claim") or "")[:900],
        "domain": item.get("domain"),
        "task_class": item.get("task_class"),
        "failure_pattern": item.get("failure_pattern"),
        "agent_id": item.get("agent_id"),
        "capability_id": item.get("capability_id"),
        "status": item.get("status"),
        "confidence": item.get("confidence"),
        "evidence_refs": list(item.get("evidence_refs") or ())[:12],
        "goal_id": metadata.get("goal_id"),
        "task_id": metadata.get("task_id"),
        "artifact_refs": list(metadata.get("artifact_refs") or ())[:8],
        "supersedes_memory_id": metadata.get("supersedes_memory_id"),
    }


def _compact_decision(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": item.get("decision_id"),
        "decision_type": item.get("decision_type"),
        "source_surface": item.get("source_surface"),
        "goal_id": item.get("goal_id"),
        "task_id": item.get("task_id"),
        "capability_id": item.get("capability_id"),
        "agent_id": item.get("agent_id"),
        "artifact_ref": item.get("artifact_ref"),
        "content": str(item.get("content") or "")[:1200],
        "evidence_refs": list(item.get("evidence_refs") or ())[:12],
        "created_at": item.get("created_at"),
    }


def _compact_competence(item: dict[str, Any]) -> dict[str, Any]:
    tested = int(item.get("tested_cases") or 0)
    return {
        "competence_id": item.get("competence_id"),
        "agent_id": item.get("agent_id"),
        "capability_id": item.get("capability_id"),
        "task_class": item.get("task_class"),
        "version": item.get("version"),
        "tested_cases": tested,
        "success_rate": (
            float(item.get("success_count") or 0) / tested if tested else None
        ),
        "failure_rate": (
            float(item.get("failure_count") or 0) / tested if tested else None
        ),
        "known_failure_modes": list(item.get("known_failure_modes") or ())[:8],
        "evidence_refs": list(item.get("evidence_refs") or ())[:12],
        "status": item.get("status"),
    }


def _compact_episode(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "episode_id": item.get("episode_id"),
        "goal_id": item.get("goal_id"),
        "task_id": item.get("task_id"),
        "agent_id": item.get("agent_id"),
        "capability_id": item.get("capability_id"),
        "task_class": item.get("task_class"),
        "status": item.get("status"),
        "input_refs": list(item.get("input_refs") or ())[:8],
        "output_refs": list(item.get("output_refs") or ())[:8],
        "artifact_refs": list(item.get("artifact_refs") or ())[:8],
        "evidence_refs": list(item.get("evidence_refs") or ())[:12],
        "run_ref": item.get("run_ref"),
        "finished_at": item.get("finished_at"),
    }


@dataclass(frozen=True)
class BoundedMemoryContext:
    goal_id: str | None
    task_class: str | None
    capability_id: str | None
    agent_id: str | None
    artifact_ref: str | None
    failure_pattern: str | None
    conversation_memory: tuple[dict[str, Any], ...]
    operational_memory: tuple[dict[str, Any], ...]
    knowledge_memory: tuple[dict[str, Any], ...]
    artifact_lineage_memory: tuple[dict[str, Any], ...]
    competence_records: tuple[dict[str, Any], ...]
    max_bytes: int
    used_bytes: int
    truncated: bool
    authority: str = "DEEPSEEK_HARNESS"
    source_of_truth: str = "canonical BR SQLite"
    obsidian_role: str = "PROJECTION_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fits(payload: dict[str, Any], max_bytes: int) -> bool:
    return len(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")) <= max_bytes


def build_bounded_memory_context(
    *,
    goal_id: str | None,
    domain: str,
    task_class: str | None = None,
    capability_id: str | None = None,
    agent_id: str | None = None,
    artifact_ref: str | None = None,
    failure_pattern: str | None = None,
    intent: str | None = None,
    max_bytes: int = 32768,
    per_class_limit: int = 8,
) -> BoundedMemoryContext:
    if not str(domain or "").strip():
        raise ValueError("domain is required for bounded memory retrieval")
    if max_bytes < 4096 or max_bytes > 262144:
        raise ValueError("bounded memory max_bytes is outside safe limits")
    per_class_limit = max(1, min(int(per_class_limit), 20))

    # CONVERSATION_MEMORY: canonical cross-surface decisions only.
    decision_candidates: list[dict[str, Any]] = []
    if goal_id:
        decision_candidates.extend(
            learning_repository.list_canonical_human_decisions(
                goal_id=goal_id, limit=per_class_limit * 3
            )
        )
    if artifact_ref:
        decision_candidates.extend(
            learning_repository.list_canonical_human_decisions(
                artifact_ref=artifact_ref, limit=per_class_limit * 2
            )
        )
    if not decision_candidates:
        decision_candidates.extend(
            learning_repository.list_canonical_human_decisions(
                capability_id=capability_id,
                agent_id=agent_id,
                limit=per_class_limit,
            )
        )
    decisions: list[dict[str, Any]] = []
    seen_decisions: set[str] = set()
    for item in decision_candidates:
        identity = str(item.get("decision_id") or "")
        if not identity or identity in seen_decisions:
            continue
        if task_class and item.get("task_id") and str(item.get("task_id")) != str(task_class):
            # task_id and task_class are different namespaces; do not hard reject.
            pass
        seen_decisions.add(identity)
        decisions.append(_compact_decision(item))
        if len(decisions) >= per_class_limit:
            break

    # OPERATIONAL_MEMORY: validated ACTIVE memories and known failures.
    memory_candidates: list[dict[str, Any]] = []
    queries = (
        {"domain": domain, "task_class": task_class, "capability_id": capability_id},
        {"domain": domain, "capability_id": capability_id},
        {"domain": domain, "task_class": task_class},
    )
    for query in queries:
        filtered = {key: value for key, value in query.items() if value is not None}
        memory_candidates.extend(
            learning_repository.list_memories(
                status="ACTIVE",
                limit=per_class_limit * 2,
                **filtered,
            )
        )
    if failure_pattern:
        memory_candidates.extend(
            learning_repository.list_memories(
                status="ACTIVE",
                memory_type="FAILURE",
                domain=domain,
                failure_pattern=failure_pattern,
                limit=per_class_limit * 2,
            )
        )

    target_tokens = _tokens(
        goal_id, task_class, capability_id, agent_id, artifact_ref,
        failure_pattern, intent,
    )

    def memory_score(item: dict[str, Any]) -> tuple[int, float, int, str]:
        metadata = dict(item.get("metadata") or {})
        score = 0
        if failure_pattern and item.get("failure_pattern") == failure_pattern:
            score += 20
        if capability_id and item.get("capability_id") == capability_id:
            score += 10
        if task_class and item.get("task_class") == task_class:
            score += 8
        if agent_id and item.get("agent_id") == agent_id:
            score += 6
        if goal_id and metadata.get("goal_id") == goal_id:
            score += 6
        if artifact_ref and artifact_ref in (metadata.get("artifact_refs") or ()):
            score += 6
        score += len(target_tokens & _tokens(
            item.get("claim"), item.get("failure_pattern"), metadata
        ))
        return (
            score,
            float(item.get("confidence") or 0.0),
            int(item.get("support_count") or 0),
            str(item.get("memory_id") or ""),
        )

    unique_memories: dict[str, dict[str, Any]] = {}
    for item in memory_candidates:
        identity = str(item.get("memory_id") or "")
        if identity:
            unique_memories[identity] = item
    ranked_memories = sorted(
        unique_memories.values(),
        key=memory_score,
        reverse=True,
    )[:per_class_limit]
    operational = [_compact_memory(item) for item in ranked_memories]

    competence = [
        _compact_competence(item)
        for item in learning_repository.list_competence(
            domain=domain,
            task_class=task_class,
            capability_id=capability_id,
            agent_id=agent_id,
            status="ACTIVE",
            limit=per_class_limit,
        )
    ]

    # KNOWLEDGE_MEMORY: evidence-backed GTA6 claims, compact and deterministic.
    knowledge: list[dict[str, Any]] = []
    if "gta6" in str(domain).casefold() or "gta" in str(intent or "").casefold():
        claim_candidates = list_memory_claims(
            scope="gta6",
            status="active",
            limit=50,
        )
        scored: list[tuple[int, float, dict[str, Any], list[dict[str, Any]]]] = []
        for claim in claim_candidates:
            evidence = list_memory_claim_evidence_for_claim(int(claim["id"]), limit=12)
            if not evidence:
                continue
            score = len(target_tokens & _tokens(claim.get("claim")))
            scored.append((
                score,
                float(claim.get("confidence") or 0.0),
                claim,
                evidence,
            ))
        for _, _, claim, evidence in sorted(
            scored, key=lambda row: (row[0], row[1], int(row[2]["id"])), reverse=True
        )[:per_class_limit]:
            knowledge.append({
                "claim_id": claim.get("id"),
                "claim": str(claim.get("claim") or "")[:900],
                "claim_type": claim.get("claim_type"),
                "confidence": claim.get("confidence"),
                "status": claim.get("status"),
                "evidence_refs": [
                    f"memory-claim-evidence:{row.get('id')}"
                    for row in evidence[:12]
                ],
                "updated_at": claim.get("updated_at"),
            })

    # ARTIFACT_LINEAGE_MEMORY: derived only from canonical HarnessEpisode lineage.
    episodes = learning_repository.list_episodes(
        domain=domain,
        task_class=task_class,
        capability_id=capability_id,
        limit=50,
    )
    lineage: list[dict[str, Any]] = []
    for episode in episodes:
        if goal_id and episode.get("goal_id") != goal_id:
            continue
        if agent_id and episode.get("agent_id") != agent_id:
            continue
        refs = {
            *[str(x) for x in (episode.get("input_refs") or ())],
            *[str(x) for x in (episode.get("output_refs") or ())],
            *[str(x) for x in (episode.get("artifact_refs") or ())],
        }
        if artifact_ref and artifact_ref not in refs:
            continue
        lineage.append(_compact_episode(episode))
        if len(lineage) >= per_class_limit:
            break

    payload = {
        "conversation_memory": decisions,
        "operational_memory": operational,
        "knowledge_memory": knowledge,
        "artifact_lineage_memory": lineage,
        "competence_records": competence,
    }
    truncated = False
    while not _fits(payload, max_bytes):
        truncated = True
        largest_key = max(
            payload,
            key=lambda key: len(json.dumps(payload[key], default=str)),
        )
        if not payload[largest_key]:
            break
        payload[largest_key].pop()

    used = len(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8"))
    return BoundedMemoryContext(
        goal_id=goal_id,
        task_class=task_class,
        capability_id=capability_id,
        agent_id=agent_id,
        artifact_ref=artifact_ref,
        failure_pattern=failure_pattern,
        conversation_memory=tuple(payload["conversation_memory"]),
        operational_memory=tuple(payload["operational_memory"]),
        knowledge_memory=tuple(payload["knowledge_memory"]),
        artifact_lineage_memory=tuple(payload["artifact_lineage_memory"]),
        competence_records=tuple(payload["competence_records"]),
        max_bytes=max_bytes,
        used_bytes=used,
        truncated=truncated,
    )
