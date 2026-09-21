from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from app.database import harness_learning_repository as repository
from app.services.harness_learning_service import HarnessEpisode, persist_episode
from app.services.memory_plane_service import record_canonical_human_decision


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_telegram_memory_candidate(
    *,
    message: str,
    state: dict[str, Any],
    human_turn: dict[str, Any],
    identity: dict[str, Any] | None,
    telegram_chat_id: int,
    telegram_user_id: int | None,
) -> dict[str, Any]:
    """Capture an explicit human remember/store request without auto-promotion."""

    text = str(message or "").strip()
    if not text:
        raise ValueError("memory candidate text is empty")
    turn_id = int(human_turn["turn_id"])
    goal_id = str(state.get("active_goal_id") or "telegram-human-memory").strip()
    evidence_ref = f"telegram-turn:{turn_id}"
    decision = record_canonical_human_decision(
        decision_type="USER_NOTE",
        source_surface="telegram",
        source_ref=evidence_ref,
        content=text,
        evidence_refs=(evidence_ref,),
        goal_id=goal_id,
        task_id=str(state.get("active_task") or "telegram-memory-candidate"),
        artifact_ref=str(state.get("active_artifact") or "") or None,
        metadata={
            "conversation_id": state.get("conversation_id"),
            "telegram_chat_id": telegram_chat_id,
            "telegram_user_id": telegram_user_id,
            "human_identity_id": (identity or {}).get("human_identity_id"),
            "thread_id": (identity or {}).get("thread_id"),
            "memory_gate_required": True,
        },
    )

    digest = sha256(
        f"{goal_id}\0{turn_id}\0{text}".encode("utf-8")
    ).hexdigest()[:20]
    now = _now()
    episode = HarnessEpisode(
        episode_id=f"episode-telegram-memory-{digest}",
        goal_id=goal_id,
        decision_id=f"decision-telegram-memory-{digest}",
        execution_id=f"execution-telegram-memory-{digest}",
        task_id="telegram-memory-candidate",
        agent_id="telegram-human-ingress",
        capability_id="telegram.input.ingest",
        domain="human-memory",
        task_class="telegram-memory-candidate",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status="COMPLETED",
        actual_outcome={
            "observed": True,
            "human_decision_id": decision["decision_id"],
            "memory_candidate_requested": True,
            "canonical_auto_promotion": False,
        },
        outcome_evidence=(evidence_ref,),
        input_refs=(evidence_ref,),
        output_refs=(f"human-decision:{decision['decision_id']}",),
        evidence_refs=(evidence_ref,),
        human_intervention=True,
        qa_results={"explicit_memory_request": "PASS"},
        cost=0.0,
        latency_seconds=0.0,
        artifact_refs=tuple(
            ref for ref in (state.get("active_artifact"),) if ref
        ),
        lineage={
            "source_surface": "telegram",
            "canonical_memory_plane": "HARNESS_LEARNING_PLANE",
            "memory_gate": "REQUIRED",
            "human_identity_id": (identity or {}).get("human_identity_id"),
            "thread_id": (identity or {}).get("thread_id"),
        },
    )
    persisted = persist_episode(episode)
    candidates = [
        item
        for item in repository.list_memories(status="CANDIDATE", limit=200)
        if persisted["episode_id"] in (item.get("source_episode_ids") or ())
    ]
    if not candidates:
        raise RuntimeError("explicit Telegram memory request did not create MemoryCandidate")
    candidate = candidates[0]
    return {
        "status": "MEMORY_CANDIDATE_CREATED",
        "answer": (
            "Anotei isso como candidato de memória com a sua origem preservada. "
            "Ainda não virou regra canônica automaticamente; o Memory Gate continua obrigatório."
        ),
        "canonical_human_decision": decision,
        "memory_candidate": candidate,
        "episode_id": persisted["episode_id"],
        "provider_independent": True,
        "provider_calls": 0,
        "CANONICAL_AUTO_PROMOTION": "NO",
        "HARNESS_EVALUATION_REQUIRED": "PASS",
        "authority": "DEEPSEEK_HARNESS",
    }
