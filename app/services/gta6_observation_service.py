from __future__ import annotations

from collections import Counter
from typing import Any

from app.database.editorial_repository import list_editorial_evaluations
from app.database.gta6_monitor_repository import get_gta6_monitor_state
from app.database.ideas_repository import list_ideas
from app.database.memory_claim_evidence_repository import list_memory_claim_evidence_for_claim
from app.database.memory_claim_repository import list_memory_claims
from app.database.memory_event_repository import list_memory_events
from app.database.memory_repository import list_memories
from app.services.memory_claim_intelligence_service import (
    analyze_memory_claim,
    claim_intelligence_to_dict,
)
from app.services.memory_claim_service import create_memory_claim
from app.database.queue_repository import list_active_queue_items, list_queue_items
from app.database.research_repository import list_research_items
from app.database.scripts_repository import list_scripts
from app.database.video_repository import list_videos
from app.database.youtube_repository import list_youtube_publications


GTA6_NEWSWIRE_URL = "https://www.rockstargames.com/newswire"


def _status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(
        str(item.get("status", "unknown"))
        for item in items
    ))


def _field_counts(
    items: list[dict[str, Any]],
    field: str,
) -> dict[str, int]:
    return dict(Counter(
        str(item.get(field, "unknown"))
        for item in items
    ))


def _recent_items(
    items: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> str:
        return str(
            item.get("updated_at")
            or item.get("observed_at")
            or item.get("created_at")
            or ""
        )

    return sorted(items, key=sort_key, reverse=True)[:limit]


def _build_knowledge_brain_snapshot() -> dict[str, Any]:
    memories = list_memories(
        memory_type="semantic",
        scope="gta6",
        status="active",
    )
    claims = list_memory_claims(
        scope="gta6",
        status="active",
        limit=100,
    )
    uncertain_claims = list_memory_claims(
        scope="gta6",
        status="uncertain",
        limit=100,
    )
    events = list_memory_events(
        scope="gta6",
        limit=100,
    )

    recent_memories = _recent_items(memories, limit=8)
    recent_claims = _recent_items(
        [*claims, *uncertain_claims],
        limit=12,
    )
    recent_events = _recent_items(events, limit=12)

    claim_intelligence: list[dict[str, Any]] = []
    evidence_signals: list[dict[str, Any]] = []
    editorial_opportunities: list[dict[str, Any]] = []

    for claim in recent_claims:
        claim_id = int(claim["id"])
        domain_claim = create_memory_claim(
            claim=claim["claim"],
            claim_type=claim["claim_type"],
            confidence=claim["confidence"],
            status=claim["status"],
            scope=claim["scope"],
            valid_at=claim.get("valid_at"),
            invalid_at=claim.get("invalid_at"),
            extraction_method=claim["extraction_method"],
        )
        intelligence = analyze_memory_claim(domain_claim)
        claim_intelligence.append(
            claim_intelligence_to_dict(intelligence)
        )

        evidence = list_memory_claim_evidence_for_claim(claim_id)
        supporting = sum(
            1 for item in evidence
            if item.get("evidence_role") == "supporting"
        )
        contradicting = sum(
            1 for item in evidence
            if item.get("evidence_role") == "contradicting"
        )

        evidence_signals.append(
            {
                "claim_id": claim_id,
                "supporting": supporting,
                "contradicting": contradicting,
                "total": len(evidence),
            }
        )

        if claim.get("status") == "uncertain":
            editorial_opportunities.append(
                {
                    "type": "investigate_uncertain_claim",
                    "claim_id": claim_id,
                    "claim": claim.get("claim"),
                    "confidence": claim.get("confidence"),
                }
            )

        if contradicting:
            editorial_opportunities.append(
                {
                    "type": "investigate_contradiction",
                    "claim_id": claim_id,
                    "claim": claim.get("claim"),
                    "contradicting_evidence": contradicting,
                }
            )

    return {
        "memory": {
            "semantic_active_count": len(memories),
            "recent": recent_memories,
        },
        "claims": {
            "active_count": len(claims),
            "uncertain_count": len(uncertain_claims),
            "recent": recent_claims,
        },
        "events": {
            "recent": recent_events,
        },
        "intelligence": claim_intelligence,
        "evidence_signals": evidence_signals,
        "editorial_opportunities": editorial_opportunities[:12],
    }


def build_gta6_observation() -> dict[str, Any]:
    research = list_research_items()
    ideas = list_ideas()
    editorial = list_editorial_evaluations()
    queue = list_queue_items()
    active_queue = list_active_queue_items()
    scripts = list_scripts()
    videos = list_videos()
    youtube = list_youtube_publications()
    monitor = get_gta6_monitor_state(GTA6_NEWSWIRE_URL)
    knowledge_brain = _build_knowledge_brain_snapshot()

    return {
        "domain": "GTA6",
        "source_of_truth": "BR SQLite + official BR repositories",
        "monitor": monitor,
        "knowledge_brain": knowledge_brain,
        "research": {
            "count": len(research),
        },
        "ideas": {
            "count": len(ideas),
            "by_status": _status_counts(ideas),
        },
        "editorial": {
            "count": len(editorial),
            "by_decision": _field_counts(editorial, "decision"),
        },
        "queue": {
            "count": len(queue),
            "by_status": _status_counts(queue),
            "active_count": len(active_queue),
            "active_by_status": _status_counts(active_queue),
        },
        "scripts": {
            "count": len(scripts),
            "by_status": _status_counts(scripts),
        },
        "videos": {
            "count": len(videos),
            "by_status": _status_counts(videos),
        },
        "youtube": {
            "count": len(youtube),
            "by_status": _status_counts(youtube),
        },
    }
