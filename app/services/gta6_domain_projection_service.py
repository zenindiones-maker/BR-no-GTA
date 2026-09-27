from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Iterable

from app.database import harness_learning_repository
from app.database.editorial_repository import list_editorial_evaluations
from app.database.gta6_monitor_repository import get_gta6_monitor_state
from app.database.ideas_repository import list_ideas
from app.database.queue_repository import list_active_queue_items, list_queue_items
from app.database.render_queue_repository import list_render_jobs
from app.database.research_repository import list_research_items
from app.database.scripts_repository import list_scripts
from app.database.video_repository import list_videos
from app.database.youtube_repository import list_youtube_publications
from app.services.gta6_knowledge_retrieval_service import retrieve_gta6_knowledge
from app.services.harness_learning_context_service import (
    load_operational_learning_context,
)


GTA6_DOMAIN_PROJECTION_SCHEMA = "GTA6DomainProjection/v1"
GTA6_DOMAIN_PROJECTION_VERSION = "1"
GTA6_BRAIN_CAPABILITY_ID = "gta6.brain.decide"
GTA6_BRAIN_AGENT_ID = "gta6-brain"
GTA6_BRAIN_TASK_CLASS = "gta6-domain-decision"

MAX_HIGH_VALUE_CLAIMS = 8
MAX_ACTIVE_EDITORIAL_ITEMS = 5
MAX_RECENT_BRAIN_DECISIONS = 4
MAX_FAILURE_MEMORIES = 4
MAX_HUMAN_CORRECTIONS = 3
MAX_BLOCKERS = 5
MAX_EVIDENCE_REFS = 96
MAX_TEXT_CHARS = 360
MAX_PROJECTION_BYTES = 65536
_EMPTY_OBSERVED_AT = "1970-01-01T00:00:00+00:00"
_MONITOR_URL = "https://www.rockstargames.com/newswire"


class GTA6DomainProjectionError(RuntimeError):
    pass


def _compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hash(value: dict[str, Any]) -> str:
    return sha256(_compact_json(value).encode("utf-8")).hexdigest()


def _short(value: Any, limit: int = MAX_TEXT_CHARS) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _count_field(
    items: Iterable[dict[str, Any]],
    field: str,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        value = item.get(field)
        key = str(value).strip() if value not in (None, "") else "unknown"
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_time(values: Iterable[Any]) -> str:
    parsed = [
        item
        for item in (_parse_time(value) for value in values)
        if item is not None
    ]
    if not parsed:
        return _EMPTY_OBSERVED_AT
    return max(parsed).isoformat()


def _freshness(value: Any, observed_at: str) -> str:
    item = _parse_time(value)
    observed = _parse_time(observed_at)
    if item is None or observed is None:
        return "UNKNOWN"
    delta = max(0.0, (observed - item).total_seconds())
    if delta <= 2 * 86400:
        return "FRESH"
    if delta <= 14 * 86400:
        return "RECENT"
    return "STALE"


def _unique_refs(values: Iterable[Any]) -> list[str]:
    return sorted({
        str(value).strip()
        for value in values
        if isinstance(value, str) and value.strip()
    })[:MAX_EVIDENCE_REFS]


def _episode_relevance(
    item: dict[str, Any],
    *,
    goal_id: str,
    task_id: str,
) -> tuple[int, int, str, str]:
    return (
        1 if str(item.get("goal_id") or "") == goal_id else 0,
        1 if str(item.get("task_id") or "") == task_id else 0,
        str(item.get("created_at") or ""),
        str(item.get("episode_id") or ""),
    )


def _project_learning(
    *,
    goal_id: str,
    task_id: str,
) -> tuple[dict[str, Any], list[str], list[Any]]:
    learning = load_operational_learning_context(
        domain="gta6-decision",
        task_class=GTA6_BRAIN_TASK_CLASS,
        capability_id=GTA6_BRAIN_CAPABILITY_ID,
        agent_id=GTA6_BRAIN_AGENT_ID,
        goal_id=goal_id,
        intent="GTA6 domain decision feedback",
    )

    episodes = [
        item
        for item in harness_learning_repository.list_episodes(
            domain="gta6-decision",
            task_class=GTA6_BRAIN_TASK_CLASS,
            capability_id=GTA6_BRAIN_CAPABILITY_ID,
            limit=24,
        )
        if str(item.get("agent_id") or "") == GTA6_BRAIN_AGENT_ID
    ]
    episodes.sort(
        key=lambda item: _episode_relevance(
            item,
            goal_id=goal_id,
            task_id=task_id,
        ),
        reverse=True,
    )
    episodes = episodes[:MAX_RECENT_BRAIN_DECISIONS]

    decisions: list[dict[str, Any]] = []
    refs: list[str] = []
    timestamps: list[Any] = []
    for item in episodes:
        outcome = dict(item.get("actual_outcome") or {})
        domain_decision = dict(outcome.get("DOMAIN_DECISION") or {})
        projection = dict(outcome.get("DOMAIN_PROJECTION") or {})
        episode_id = str(item.get("episode_id") or "")
        episode_ref = f"episode:{episode_id}" if episode_id else None
        if episode_ref:
            refs.append(episode_ref)
        refs.extend(str(ref) for ref in item.get("evidence_refs") or ())
        timestamps.extend((item.get("created_at"), item.get("finished_at")))
        decisions.append({
            "episode_ref": episode_ref,
            "decision_id": item.get("decision_id"),
            "action": domain_decision.get("action") or "UNKNOWN",
            "reason": _short(domain_decision.get("reason")),
            "priority": domain_decision.get("priority") or "UNKNOWN",
            "confidence": domain_decision.get("confidence"),
            "outcome": {
                "success": outcome.get("success"),
                "status": item.get("status"),
                "failure_class": outcome.get("FAILURE_CLASS"),
            },
            "projection_ref": projection.get("projection_ref"),
            "projection_sha256": projection.get("content_sha256"),
            "created_at": item.get("created_at"),
        })

    failures = harness_learning_repository.list_memories(
        status="ACTIVE",
        memory_type="FAILURE",
        domain="gta6-decision",
        task_class=GTA6_BRAIN_TASK_CLASS,
        capability_id=GTA6_BRAIN_CAPABILITY_ID,
        limit=20,
    )[:MAX_FAILURE_MEMORIES]
    failure_rows: list[dict[str, Any]] = []
    for item in failures:
        memory_id = str(item.get("memory_id") or "")
        if memory_id:
            refs.append(f"memory:{memory_id}")
        refs.extend(str(ref) for ref in item.get("evidence_refs") or ())
        timestamps.extend((item.get("last_verified_at"), item.get("created_at")))
        failure_rows.append({
            "memory_ref": f"memory:{memory_id}" if memory_id else None,
            "failure_pattern": item.get("failure_pattern"),
            "summary": _short(item.get("claim")),
            "confidence": item.get("confidence"),
            "source_episode_ids": list(item.get("source_episode_ids") or ())[:4],
            "evidence_refs": _unique_refs(item.get("evidence_refs") or ()),
            "last_verified_at": item.get("last_verified_at"),
        })

    candidates = harness_learning_repository.list_human_corrections(
        status="CANDIDATE",
        limit=30,
    )
    corrections: list[tuple[tuple[int, int, str, str], dict[str, Any]]] = []
    for item in candidates:
        affected_capability = str(item.get("affected_capability") or "")
        affected_agent = str(item.get("affected_agent") or "")
        correction_goal = str(item.get("goal_id") or "")
        correction_task = str(item.get("task_id") or "")
        if affected_capability not in {"", GTA6_BRAIN_CAPABILITY_ID}:
            continue
        if affected_agent not in {"", GTA6_BRAIN_AGENT_ID}:
            continue
        if correction_goal not in {"", goal_id}:
            continue
        if correction_task not in {"", task_id}:
            continue
        relevance = (
            1 if correction_goal == goal_id else 0,
            1 if correction_task == task_id else 0,
            str(item.get("created_at") or ""),
            str(item.get("correction_id") or ""),
        )
        corrections.append((relevance, item))
    corrections.sort(key=lambda pair: pair[0], reverse=True)

    correction_rows: list[dict[str, Any]] = []
    for _, item in corrections[:MAX_HUMAN_CORRECTIONS]:
        correction_id = str(item.get("correction_id") or "")
        if correction_id:
            refs.append(f"human-correction:{correction_id}")
        refs.extend(str(ref) for ref in item.get("evidence_refs") or ())
        timestamps.append(item.get("created_at"))
        correction_rows.append({
            "correction_ref": (
                f"human-correction:{correction_id}" if correction_id else None
            ),
            "summary": _short(item.get("desired_behavior")),
            "undesired_behavior": _short(item.get("undesired_behavior")),
            "scope": item.get("scope"),
            "created_at": item.get("created_at"),
            "evidence_refs": _unique_refs(item.get("evidence_refs") or ()),
        })

    human_decisions = harness_learning_repository.list_canonical_human_decisions(
        goal_id=goal_id,
        limit=12,
    )
    human_decisions = [
        item
        for item in human_decisions
        if str(item.get("capability_id") or "") in {"", GTA6_BRAIN_CAPABILITY_ID}
        and str(item.get("agent_id") or "") in {"", GTA6_BRAIN_AGENT_ID}
    ][:MAX_HUMAN_CORRECTIONS]
    decision_rows: list[dict[str, Any]] = []
    for item in human_decisions:
        decision_id = str(item.get("decision_id") or "")
        if decision_id:
            refs.append(f"human-decision:{decision_id}")
        refs.extend(str(ref) for ref in item.get("evidence_refs") or ())
        timestamps.append(item.get("created_at"))
        decision_rows.append({
            "decision_ref": f"human-decision:{decision_id}" if decision_id else None,
            "decision_type": item.get("decision_type"),
            "summary": _short(item.get("content")),
            "created_at": item.get("created_at"),
            "evidence_refs": _unique_refs(item.get("evidence_refs") or ()),
        })

    return {
        "recent_brain_decisions": decisions,
        "relevant_failure_memories": failure_rows,
        "relevant_human_corrections": correction_rows,
        "relevant_human_decisions": decision_rows,
        "learning_context": {
            "retrieved_memory_ids": list(
                learning.get("retrieved_memory_ids") or ()
            )[:16],
            "retrieved_failure_memory_ids": list(
                learning.get("retrieved_failure_memory_ids") or ()
            )[:16],
            "retrieved_human_feedback_ids": list(
                learning.get("retrieved_human_feedback_ids") or ()
            )[:16],
            "retrieved_human_decision_ids": list(
                learning.get("retrieved_human_decision_ids") or ()
            )[:16],
            "learning_participated": bool(learning.get("learning_participated")),
        },
    }, refs, timestamps


def build_gta6_domain_projection(
    *,
    mission_id: str,
    task_id: str,
    goal_id: str,
) -> dict[str, Any]:
    for name, value in (
        ("mission_id", mission_id),
        ("task_id", task_id),
        ("goal_id", goal_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")

    research_items = list_research_items()
    ideas = list_ideas()
    editorial = list_editorial_evaluations()
    queue = list_queue_items()
    active_queue = list_active_queue_items()
    scripts = list_scripts()
    videos = list_videos()
    youtube = list_youtube_publications()
    render_jobs = list_render_jobs()
    monitor_state = get_gta6_monitor_state(_MONITOR_URL)

    retrieval = retrieve_gta6_knowledge(
        query=(
            "GTA VI official evidence novelty current research editorial "
            f"production goal {goal_id}"
        ),
        limit=MAX_HIGH_VALUE_CLAIMS,
        max_context_bytes=24000,
        include_history=False,
    )
    knowledge_units = list(retrieval.get("knowledge_units") or ())
    learning_projection, learning_refs, learning_times = _project_learning(
        goal_id=goal_id,
        task_id=task_id,
    )

    all_times: list[Any] = [
        *(item.get("published_at") for item in research_items),
        *(item.get("collected_at") for item in research_items),
        *(item.get("created_at") for item in editorial),
        *(item.get("updated_at") for item in queue),
        *(item.get("updated_at") for item in scripts),
        *(item.get("created_at") for item in videos),
        *(item.get("updated_at") for item in youtube),
        *(item.get("updated_at") for item in render_jobs),
        *(item.get("observed_at") for item in knowledge_units),
        *learning_times,
    ]
    if monitor_state:
        all_times.append(monitor_state.get("updated_at"))
    observed_at = _latest_time(all_times)

    summary = {
        "research_count": len(research_items),
        "ideas_count": len(ideas),
        "ideas_by_status": _count_field(ideas, "status"),
        "editorial_count": len(editorial),
        "editorial_by_decision": _count_field(editorial, "decision"),
        "queue_count": len(queue),
        "queue_by_status": _count_field(queue, "status"),
        "active_queue_count": len(active_queue),
        "active_queue_by_status": _count_field(active_queue, "status"),
        "scripts_count": len(scripts),
        "scripts_by_status": _count_field(scripts, "status"),
        "videos_count": len(videos),
        "videos_by_status": _count_field(videos, "status"),
        "youtube_count": len(youtube),
        "youtube_by_status": _count_field(youtube, "status"),
    }

    monitor = {
        "source_identity": _MONITOR_URL,
        "last_checked_at": (
            monitor_state.get("updated_at") if monitor_state else None
        ),
        "last_changed_at": "UNKNOWN",
        "freshness_status": (
            _freshness(monitor_state.get("updated_at"), observed_at)
            if monitor_state else "UNAVAILABLE"
        ),
        "change_detected": "UNKNOWN",
        "fetch_result_state": "OBSERVED" if monitor_state else "UNAVAILABLE",
        "known_blocker": (
            None if monitor_state else "MONITOR_STATE_UNAVAILABLE"
        ),
        "evidence_ref": (
            f"gta6-monitor-state:{monitor_state.get('id')}"
            if monitor_state and monitor_state.get("id") is not None
            else None
        ),
    }

    research_rows: list[dict[str, Any]] = []
    for item in knowledge_units[:MAX_HIGH_VALUE_CLAIMS]:
        novelty = dict(item.get("novelty") or {})
        scores = dict(item.get("scores") or {})
        research_rows.append({
            "claim_id": item.get("claim_id"),
            "claim": _short(item.get("claim")),
            "claim_type": item.get("claim_type"),
            "status": item.get("status"),
            "brain_status": item.get("brain_status"),
            "confidence": item.get("confidence"),
            "source_id": item.get("source_id"),
            "source_type": item.get("source_type"),
            "authority_class": item.get("authority_class"),
            "published_at": item.get("published_at"),
            "observed_at": item.get("observed_at"),
            "evidence_ref": item.get("evidence_ref"),
            "evidence_class": item.get("evidence_class"),
            "freshness": scores.get("freshness"),
            "world_novelty": novelty.get("world") or "UNKNOWN",
            "knowledge_novelty": novelty.get("knowledge") or "UNKNOWN",
            "editorial_novelty": novelty.get("editorial") or "UNKNOWN",
            "hybrid_score": scores.get("hybrid"),
        })
    official_count = sum(
        1
        for item in research_rows
        if str(item.get("authority_class") or "").upper() == "OFFICIAL"
    )
    research = {
        "actionable_gap_count": "UNKNOWN",
        "recent_high_value_claims": research_rows,
        "official_source_coverage": (
            round(official_count / len(research_rows), 4)
            if research_rows else "UNKNOWN"
        ),
        "freshness": (
            _freshness(
                max(
                    (
                        str(item.get("observed_at"))
                        for item in research_rows
                        if item.get("observed_at")
                    ),
                    default=None,
                ),
                observed_at,
            )
            if research_rows else "UNKNOWN"
        ),
        "novelty_state": (
            sorted({
                str(item.get("knowledge_novelty") or "UNKNOWN")
                for item in research_rows
            })
            if research_rows else ["UNKNOWN"]
        ),
        "contradiction_count": "UNKNOWN",
        "unsupported_claim_count": sum(
            1 for item in research_rows if not item.get("evidence_ref")
        ),
        "research_blockers": (
            [] if research_rows
            else ["NO_RELEVANT_CANONICAL_RETRIEVAL_RESULT"]
        )[:MAX_BLOCKERS],
        "retrieval_mode": retrieval.get("retrieval_mode"),
    }

    ideas_by_id = {
        int(item["id"]): item
        for item in ideas
        if item.get("id") is not None
    }
    scripts_by_idea: dict[int, list[dict[str, Any]]] = {}
    for item in scripts:
        idea_id = item.get("idea_id")
        if isinstance(idea_id, int):
            scripts_by_idea.setdefault(idea_id, []).append(item)
    latest_eval: dict[int, dict[str, Any]] = {}
    for item in editorial:
        idea_id = item.get("idea_id")
        if isinstance(idea_id, int):
            current = latest_eval.get(idea_id)
            if current is None or int(item.get("id") or 0) > int(current.get("id") or 0):
                latest_eval[idea_id] = item

    editorial_items: list[dict[str, Any]] = []
    editorial_refs: list[str] = []
    for item in active_queue[:MAX_ACTIVE_EDITORIAL_ITEMS]:
        idea_id = item.get("idea_id")
        idea = ideas_by_id.get(idea_id, {}) if isinstance(idea_id, int) else {}
        evaluation = latest_eval.get(idea_id, {}) if isinstance(idea_id, int) else {}
        idea_scripts = scripts_by_idea.get(idea_id, []) if isinstance(idea_id, int) else []
        latest_script_for_idea = max(
            idea_scripts,
            key=lambda value: (
                int(value.get("version") or 0),
                int(value.get("id") or 0),
            ),
            default=None,
        )
        queue_id = item.get("id")
        if queue_id is not None:
            editorial_refs.append(f"editorial-queue:{queue_id}")
        if evaluation.get("id") is not None:
            editorial_refs.append(
                f"editorial-evaluation:{evaluation.get('id')}"
            )
        editorial_items.append({
            "queue_id": queue_id,
            "idea_id": idea_id,
            "topic": _short(idea.get("title"), 220),
            "status": item.get("status"),
            "priority": item.get("priority"),
            "priority_score": item.get("priority_score"),
            "editorial_decision": evaluation.get("decision") or "UNKNOWN",
            "novelty_signal": evaluation.get("novelty"),
            "evidence_gate": "UNKNOWN",
            "novelty_gate": "UNKNOWN",
            "script_readiness": (
                latest_script_for_idea.get("status")
                if latest_script_for_idea else "UNKNOWN"
            ),
            "updated_at": item.get("updated_at"),
        })
    editorial_state = {
        "active_editorial_items": editorial_items,
        "current_goal": goal_id,
        "evidence_gate": "UNKNOWN",
        "novelty_gate": "UNKNOWN",
        "script_readiness": (
            editorial_items[0]["script_readiness"]
            if editorial_items else "UNKNOWN"
        ),
        "supported_duration_minutes": "UNKNOWN",
        "human_editorial_decision_state": "UNKNOWN",
        "pending_blocker": (
            None if editorial_items else "NO_ACTIVE_EDITORIAL_ITEM"
        ),
    }

    latest_script = max(
        scripts,
        key=lambda item: (
            int(item.get("version") or 0),
            int(item.get("id") or 0),
        ),
        default=None,
    )
    latest_video = max(
        videos,
        key=lambda item: int(item.get("id") or 0),
        default=None,
    )
    latest_youtube = max(
        youtube,
        key=lambda item: int(item.get("id") or 0),
        default=None,
    )
    latest_render = max(
        render_jobs,
        key=lambda item: int(item.get("id") or 0),
        default=None,
    )
    known_failures: list[str] = []
    if latest_render and str(latest_render.get("status") or "").lower() == "failed":
        known_failures.append("RENDER_FAILED")
    if latest_youtube and str(latest_youtube.get("status") or "").lower() == "failed":
        known_failures.append("YOUTUBE_FAILED")
    production_readiness = (
        "BLOCKED"
        if known_failures
        else "AVAILABLE"
        if latest_script or latest_render or latest_video
        else "NOT_READY"
    )
    if latest_render and str(latest_render.get("status") or "") in {"queued", "running"}:
        next_deliverable = "RENDER"
    elif latest_video and str(latest_video.get("status") or "") == "ready":
        next_deliverable = "YOUTUBE_PRIVATE_REVIEW"
    elif latest_script:
        next_deliverable = "PRODUCTION_PREP"
    else:
        next_deliverable = "SCRIPT"

    production = {
        "next_deliverable": next_deliverable,
        "script_status": (
            latest_script.get("status") if latest_script else "UNKNOWN"
        ),
        "voice_status": "UNKNOWN",
        "pronunciation_gate": "UNKNOWN",
        "media_status": (
            latest_video.get("status") if latest_video else "UNKNOWN"
        ),
        "render_status": (
            latest_render.get("status") if latest_render else "UNKNOWN"
        ),
        "qa_status": "UNKNOWN",
        "youtube_private_review_readiness": (
            "CANDIDATE"
            if latest_youtube
            and str(latest_youtube.get("privacy_status") or "") == "private"
            and str(latest_youtube.get("status") or "") in {
                "pending", "uploaded", "published"
            }
            else "UNKNOWN"
        ),
        "blocking_gate": known_failures[0] if known_failures else "UNKNOWN",
        "readiness": production_readiness,
    }

    corrections = list(
        learning_projection["relevant_human_corrections"]
    )
    human_decisions = list(
        learning_projection["relevant_human_decisions"]
    )
    review = {
        "pending_human_review": "UNKNOWN",
        "last_relevant_human_decision": (
            human_decisions[0] if human_decisions else None
        ),
        "last_relevant_human_feedback": (
            corrections[0] if corrections else None
        ),
        "blocking_review_gate": "UNKNOWN",
    }

    readiness = {
        "research": (
            "AVAILABLE" if research_rows or research_items else "NEEDS_RESEARCH"
        ),
        "editorial": "AVAILABLE" if active_queue else "IDLE",
        "production": production_readiness,
        "review": "UNKNOWN",
    }

    evidence_refs: list[str] = []
    if monitor.get("evidence_ref"):
        evidence_refs.append(str(monitor["evidence_ref"]))
    evidence_refs.extend(
        str(item.get("evidence_ref"))
        for item in research_rows
        if item.get("evidence_ref")
    )
    evidence_refs.extend(editorial_refs)
    evidence_refs.extend(learning_refs)
    if latest_script and latest_script.get("id") is not None:
        evidence_refs.append(f"script:{latest_script['id']}")
    if latest_video and latest_video.get("id") is not None:
        evidence_refs.append(f"video:{latest_video['id']}")
    if latest_render and latest_render.get("id") is not None:
        evidence_refs.append(f"render-job:{latest_render['id']}")
    if latest_youtube and latest_youtube.get("id") is not None:
        evidence_refs.append(
            f"youtube-publication:{latest_youtube['id']}"
        )

    projection = {
        "schema": GTA6_DOMAIN_PROJECTION_SCHEMA,
        "projection_version": GTA6_DOMAIN_PROJECTION_VERSION,
        "projection_owner": "DEEPSEEK_HARNESS_BOUNDARY",
        "brain_projection_authority": "NONE",
        "mission_id": mission_id.strip(),
        "task_id": task_id.strip(),
        "goal_id": goal_id.strip(),
        "observed_at": observed_at,
        "built_at": observed_at,
        "summary": summary,
        "monitor": monitor,
        "research": research,
        "editorial": editorial_state,
        "production": production,
        "review": review,
        "decision_feedback": learning_projection,
        "readiness": readiness,
        "evidence_refs": _unique_refs(evidence_refs),
        "source_versions": {
            "projection_schema": GTA6_DOMAIN_PROJECTION_SCHEMA,
            "projection_policy": "gta6-domain-projection-policy/v1",
            "learning_context": "operational-learning-context/v1",
            "knowledge_retrieval": "gta6-knowledge-retrieval/v1",
            "gta6_brain_capability": "1",
        },
    }
    projection["content_sha256"] = _hash(projection)
    encoded = _compact_json(projection).encode("utf-8")
    if len(encoded) > MAX_PROJECTION_BYTES:
        raise GTA6DomainProjectionError(
            "GTA6 domain projection exceeds bounded byte policy"
        )
    return projection


def gta6_domain_projection_ref(projection: dict[str, Any]) -> str:
    if projection.get("schema") != GTA6_DOMAIN_PROJECTION_SCHEMA:
        raise GTA6DomainProjectionError(
            "invalid GTA6 domain projection schema"
        )
    digest = str(projection.get("content_sha256") or "")
    if len(digest) != 64:
        raise GTA6DomainProjectionError(
            "invalid GTA6 domain projection hash"
        )
    return f"gta6-domain-projection:sha256:{digest}"
