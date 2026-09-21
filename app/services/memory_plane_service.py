from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Iterable

from app.database import harness_learning_repository as repository
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_learning_service import record_memory


CONVERSATION_MEMORY = "CONVERSATION_MEMORY"
OPERATIONAL_MEMORY = "OPERATIONAL_MEMORY"
KNOWLEDGE_MEMORY = "KNOWLEDGE_MEMORY"
ARTIFACT_LINEAGE_MEMORY = "ARTIFACT_LINEAGE_MEMORY"
MEMORY_CLASSES = {
    CONVERSATION_MEMORY,
    OPERATIONAL_MEMORY,
    KNOWLEDGE_MEMORY,
    ARTIFACT_LINEAGE_MEMORY,
}

MEMORY_EVALUATION_DECISIONS = {
    "PROMOTE",
    "REJECT",
    "HUMAN_REVIEW",
    "SUPERSEDE",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _refs(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(value).strip()
        for value in values
        if str(value).strip()
    ))


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def record_canonical_human_decision(
    *,
    decision_type: str,
    source_surface: str,
    source_ref: str,
    content: str,
    evidence_refs: Iterable[str],
    goal_id: str | None = None,
    task_id: str | None = None,
    capability_id: str | None = None,
    agent_id: str | None = None,
    artifact_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = str(decision_type or "").strip().upper()
    if normalized_type not in {
        "APPROVAL", "REJECTION", "FEEDBACK", "INSTRUCTION", "CANCEL", "USER_NOTE",
    }:
        raise ValueError("unsupported canonical human decision type")
    surface = str(source_surface or "").strip().lower()
    reference = str(source_ref or "").strip()
    body = str(content or "").strip()
    refs = _refs(evidence_refs)
    if not surface or not reference or not body or not refs:
        raise ValueError("canonical human decision requires surface, source, content and evidence")
    payload = {
        "decision_type": normalized_type,
        "source_surface": surface,
        "source_ref": reference,
        "goal_id": goal_id,
        "task_id": task_id,
        "capability_id": capability_id,
        "agent_id": agent_id,
        "artifact_ref": artifact_ref,
        "content": body,
    }
    record = {
        **payload,
        "decision_id": _stable_id("human-decision", payload),
        "evidence_refs": refs,
        "metadata": {
            "memory_class": CONVERSATION_MEMORY,
            "canonical_memory_plane": "HARNESS_LEARNING_PLANE",
            **dict(metadata or {}),
        },
        "created_at": _utcnow(),
    }
    return repository.insert_canonical_human_decision(record)


def infer_failure_pattern(episode: dict[str, Any]) -> str:
    text = " ".join(
        str(value or "")
        for value in (
            episode.get("error"),
            (episode.get("actual_outcome") or {}).get("error"),
            (episode.get("actual_outcome") or {}).get("provider_error"),
        )
    ).casefold()
    if "codex_device_auth_wait_timeout" in text or (
        "device auth" in text and "runner" in text and "waiting" in text
    ):
        return "codex_device_auth_wait_timeout"
    if "free tier" in text and ("403" in text or "opencode" in text):
        return "opencode_free_tier_403"
    if "semantic" in text and "tool" in text:
        return "semantic_tools_used"
    if "review" in text and ("loop" in text or "reopen" in text or "changes" in text):
        return "hermes_review_loop"
    if "pending_action" in text or ("restart" in text and "pending" in text):
        return "pending_action_restart_loss"
    if (
        "read_set exceeds mission path scope" in text
        or "request_scope_expansion" in text
        or ("read_set" in text and "mission path scope" in text)
    ):
        return "task_read_set_exceeds_mission_path_scope"
    compact = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:64]
    if compact:
        return compact
    return "observed_execution_failure"


def capture_episode_memory_candidate(episode: dict[str, Any]) -> dict[str, Any] | None:
    status = str(episode.get("status") or "").upper()
    if status not in {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}:
        return None
    episode_id = str(episode.get("episode_id") or "").strip()
    evidence = _refs([
        *(episode.get("evidence_refs") or ()),
        *(episode.get("outcome_evidence") or ()),
    ])
    if not episode_id or not evidence:
        return None

    failed = status != "COMPLETED"
    failure_pattern = infer_failure_pattern(episode) if failed else None
    task_id = str(episode.get("task_id") or "")
    capability_id = str(episode.get("capability_id") or "")
    agent_id = str(episode.get("agent_id") or "")
    claim = (
        f"Observed failure for {capability_id} task {task_id}: "
        f"{failure_pattern}"
        if failed
        else f"Observed execution outcome for {capability_id} task {task_id}."
    )
    artifacts = list(episode.get("artifact_refs") or ())
    metadata = {
        "memory_class": OPERATIONAL_MEMORY,
        "candidate_origin": "HARNESS_EPISODE",
        "evaluation_required": True,
        "goal_id": episode.get("goal_id"),
        "task_id": task_id,
        "artifact_refs": artifacts,
        "run_ref": episode.get("run_ref"),
        "status_observed": status,
        "canonical_auto_promotion": False,
    }
    return record_memory(
        memory_type="FAILURE" if failed else "EPISODIC",
        claim=claim,
        domain=str(episode.get("domain") or "unknown"),
        task_class=str(episode.get("task_class") or "") or None,
        failure_pattern=failure_pattern,
        source_episode_ids=(episode_id,),
        evidence_refs=evidence,
        agent_id=agent_id or None,
        capability_id=capability_id or None,
        skill_id=episode.get("skill_id"),
        skill_version=episode.get("skill_version"),
        source_versions=dict(episode.get("source_versions") or {}),
        metadata=metadata,
        support_count=1,
        contradiction_count=0,
        confidence=0.85 if failed else 0.6,
        status="CANDIDATE",
        identity_payload={
            "candidate_origin": "HARNESS_EPISODE",
            "episode_id": episode_id,
            "capability_id": capability_id,
            "task_id": task_id,
            "status": status,
        },
    )


def evaluate_memory_candidate(
    *,
    memory_id: str,
    decision: str,
    reason: str,
    evidence_refs: Iterable[str],
    authorization,
    supersedes_memory_id: str | None = None,
) -> dict[str, Any]:
    normalized = str(decision or "").strip().upper()
    if normalized not in MEMORY_EVALUATION_DECISIONS:
        raise ValueError("invalid memory evaluation decision")
    why = str(reason or "").strip()
    refs = _refs(evidence_refs)
    if not why or not refs:
        raise ValueError("memory evaluation requires reason and evidence")

    memory = repository.get_memory(memory_id)
    if memory is None:
        raise ValueError("memory candidate not found")
    if memory.get("status") != "CANDIDATE":
        raise PermissionError("only CANDIDATE memory may enter the memory evaluation gate")

    auth = validate_harness_authorization(
        authorization,
        expected_action="DECISION",
        expected_subject=f"learning:memory:{memory_id}",
    )
    now = _utcnow()
    metadata = {
        "memory_gate_decision": normalized,
        "promotion_reason": why,
        "evaluated_at": now,
        "evaluation_required": False if normalized in {"PROMOTE", "REJECT", "SUPERSEDE"} else True,
    }

    if normalized == "PROMOTE":
        updated = repository.update_memory_lifecycle(
            memory_id,
            status="ACTIVE",
            metadata_updates=metadata,
            last_verified_at=now,
        )
    elif normalized == "REJECT":
        updated = repository.update_memory_lifecycle(
            memory_id,
            status="RETIRED",
            metadata_updates=metadata,
            last_verified_at=now,
        )
    elif normalized == "HUMAN_REVIEW":
        updated = repository.update_memory_lifecycle(
            memory_id,
            status="CANDIDATE",
            metadata_updates={**metadata, "pending_human_review": True},
            last_verified_at=now,
        )
    else:
        if not supersedes_memory_id:
            raise ValueError("SUPERSEDE requires supersedes_memory_id")
        previous = repository.get_memory(supersedes_memory_id)
        if previous is None:
            raise ValueError("superseded memory not found")
        if previous.get("status") != "ACTIVE":
            raise PermissionError("only ACTIVE memory may be superseded")
        repository.update_memory_lifecycle(
            supersedes_memory_id,
            status="SUPERSEDED",
            metadata_updates={
                "superseded_by_memory_id": memory_id,
                "supersession_evidence_refs": list(refs),
                "promotion_reason": why,
                "superseded_at": now,
            },
            last_verified_at=now,
        )
        updated = repository.update_memory_lifecycle(
            memory_id,
            status="ACTIVE",
            metadata_updates={
                **metadata,
                "supersedes_memory_id": supersedes_memory_id,
                "supersession_evidence_refs": list(refs),
            },
            last_verified_at=now,
        )

    evaluation_payload = {
        "memory_id": memory_id,
        "decision": normalized,
        "reason": why,
        "evidence_refs": refs,
        "supersedes_memory_id": supersedes_memory_id,
        "authorization_id": auth.authorization_id,
    }
    evaluation = repository.insert_memory_evaluation({
        **evaluation_payload,
        "evaluation_id": _stable_id("memory-eval", evaluation_payload),
        "authority": auth.authority,
        "created_at": now,
    })
    consume_harness_authorization(auth)
    return {
        "status": "EVALUATED",
        "authority": auth.authority,
        "memory": updated,
        "evaluation": evaluation,
        "canonical_auto_promotion": False,
    }
