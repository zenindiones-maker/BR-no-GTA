from datetime import datetime, timezone

from app.database import continuous_operation_repository as continuous_repository
from app.database import gta6_brain_repository as brain_repository
from app.database.memory_claim_repository import insert_memory_claim
from app.services.gta6_knowledge_retrieval_service import retrieve_gta6_knowledge
from app.services.memory_claim_service import create_memory_claim


NOW = "2026-09-21T23:00:00+00:00"


def _claim(text: str, *, source_id: str, url: str, source_type: str, subject: str) -> int:
    claim_id = insert_memory_claim(
        create_memory_claim(
            claim=text,
            claim_type="fact",
            confidence=9.5 if source_type == "PRIMARY_SOURCE" else 7.0,
            status="active",
            scope="gta6",
            extraction_method="test-autonomous-brain",
        )
    )
    continuous_repository.upsert_claim_lineage({
        "claim_id": claim_id,
        "subject": subject,
        "source_id": source_id,
        "source_url": url,
        "source_type": source_type,
        "published_at": "2026-09-20T12:00:00+00:00",
        "observed_at": NOW,
        "evidence_ref": f"evidence:{source_id}:{claim_id}",
        "evidence_class": "OFFICIAL" if source_type == "PRIMARY_SOURCE" else "UNVERIFIED",
        "status_snapshot": "ACTIVE",
        "related_claims": [],
        "metadata": {},
    })
    return claim_id


def test_source_registry_raw_evidence_and_frontier_are_idempotent():
    source = brain_repository.upsert_source({
        "source_id": "source-rockstar-vi",
        "url": "https://www.rockstargames.com/VI",
        "domain": "rockstargames.com",
        "source_type": "PRIMARY_SOURCE",
        "authority_class": "ROCKSTAR_OFFICIAL",
        "reliability_score": 1.0,
        "discovered_at": NOW,
        "last_checked_at": NOW,
        "last_changed_at": NOW,
        "content_hash": "abc123",
        "refresh_priority": 100,
        "refresh_interval_seconds": 21600,
        "refresh_state": "CURRENT",
        "active": True,
        "provenance": {"authority": "DEEPSEEK_HARNESS"},
    })
    assert source["authority_class"] == "ROCKSTAR_OFFICIAL"
    assert brain_repository.get_source_by_url(source["url"])["source_id"] == source["source_id"]

    evidence, duplicate = brain_repository.insert_evidence({
        "evidence_id": "evidence-rockstar-abc123",
        "source_id": source["source_id"],
        "url": source["url"],
        "publication_date": "2026-09-20T12:00:00+00:00",
        "observed_at": NOW,
        "excerpt": "Rockstar confirms a GTA VI fact about Vice City.",
        "content_hash": "content-hash-1",
        "source_type": "PRIMARY_SOURCE",
        "provenance": {"url": source["url"], "observed_at": NOW},
        "extraction_method": "direct_source_fetch",
    })
    assert duplicate is False
    again, duplicate = brain_repository.insert_evidence({
        **evidence,
        "evidence_id": "different-id-same-content",
    })
    assert duplicate is True
    assert again["evidence_id"] == evidence["evidence_id"]

    question = brain_repository.upsert_frontier_question({
        "question_id": "question-police-behavior",
        "question": "Existe mudança comprovada no comportamento policial?",
        "topic": "police",
        "entity_ids": [],
        "priority": 90,
        "current_confidence": 0.2,
        "supporting_evidence": [],
        "contradictory_evidence": [],
        "missing_evidence": ["official gameplay evidence"],
        "next_research_strategy": "watch official Rockstar GTA VI sources",
        "sources_to_watch": [source["source_id"]],
        "created_at": NOW,
        "status": "OPEN",
    })
    assert question["status"] == "OPEN"
    assert brain_repository.list_frontier(limit=5)[0]["question_id"] == question["question_id"]


def test_hybrid_retrieval_is_bounded_and_prefers_official_source():
    official_url = "https://www.rockstargames.com/VI"
    community_url = "https://www.reddit.com/r/GTA6/example"
    brain_repository.upsert_source({
        "source_id": "official",
        "url": official_url,
        "domain": "rockstargames.com",
        "source_type": "PRIMARY_SOURCE",
        "authority_class": "ROCKSTAR_OFFICIAL",
        "reliability_score": 1.0,
        "discovered_at": NOW,
        "last_checked_at": NOW,
        "refresh_priority": 100,
        "refresh_interval_seconds": 21600,
        "refresh_state": "CURRENT",
        "active": True,
    })
    brain_repository.upsert_source({
        "source_id": "community",
        "url": community_url,
        "domain": "reddit.com",
        "source_type": "COMMUNITY",
        "authority_class": "COMMUNITY",
        "reliability_score": 0.3,
        "discovered_at": NOW,
        "last_checked_at": NOW,
        "refresh_priority": 20,
        "refresh_interval_seconds": 86400,
        "refresh_state": "CURRENT",
        "active": True,
    })

    official_claim = _claim(
        "Lucia appears in official GTA VI material connected to Vice City.",
        source_id="official",
        url=official_url,
        source_type="PRIMARY_SOURCE",
        subject="Lucia",
    )
    community_claim = _claim(
        "Lucia appears in a community discussion connected to Vice City.",
        source_id="community",
        url=community_url,
        source_type="COMMUNITY",
        subject="Lucia",
    )
    entity_id = "entity-lucia"
    brain_repository.upsert_entity({
        "entity_id": entity_id,
        "entity_type": "CHARACTER",
        "canonical_name": "Lucia",
        "aliases": ["Lucia Caminos"],
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "status": "ACTIVE",
    })
    for claim_id in (official_claim, community_claim):
        brain_repository.upsert_claim_metadata({
            "claim_id": claim_id,
            "subject_entity_id": entity_id,
            "brain_status": "ACTIVE",
            "first_seen_at": NOW,
            "last_verified_at": NOW,
            "related_claims": [],
            "used_in_content": [],
            "world_novelty": "HIGH",
            "knowledge_novelty": "NEW",
            "editorial_novelty": "UNUSED",
            "freshness_class": "HIGH",
        })

    result = retrieve_gta6_knowledge(
        query="O que sabemos sobre Lucia em Vice City?",
        limit=5,
        max_context_bytes=8192,
    )
    assert result["bounded_context"] is True
    assert result["context_bytes"] <= 8192
    assert result["semantic_embedding_used"] is False
    assert result["semantic_embedding_status"] == "NOT_PROMOTED"
    assert len(result["knowledge_units"]) == 2
    assert result["knowledge_units"][0]["claim_id"] == official_claim
    assert result["knowledge_units"][0]["authority_class"] == "ROCKSTAR_OFFICIAL"
    assert (
        result["knowledge_units"][0]["scores"]["source_quality"]
        > result["knowledge_units"][1]["scores"]["source_quality"]
    )


def test_claim_metadata_preserves_supersession_history():
    old_claim = _claim(
        "A release detail was previously stated one way.",
        source_id="old-source",
        url="https://www.rockstargames.com/VI",
        source_type="PRIMARY_SOURCE",
        subject="Release",
    )
    new_claim = _claim(
        "A release detail is now stated differently.",
        source_id="new-source",
        url="https://www.rockstargames.com/VI",
        source_type="PRIMARY_SOURCE",
        subject="Release",
    )
    brain_repository.upsert_claim_metadata({
        "claim_id": old_claim,
        "brain_status": "SUPERSEDED",
        "first_seen_at": NOW,
        "last_verified_at": NOW,
        "superseded_by_claim_id": new_claim,
        "related_claims": [new_claim],
        "used_in_content": [],
        "world_novelty": "OLD",
        "knowledge_novelty": "KNOWN",
        "editorial_novelty": "UNUSED",
        "freshness_class": "LOW",
    })
    brain_repository.upsert_claim_metadata({
        "claim_id": new_claim,
        "brain_status": "ACTIVE",
        "first_seen_at": NOW,
        "last_verified_at": NOW,
        "related_claims": [old_claim],
        "used_in_content": [],
        "world_novelty": "HIGH",
        "knowledge_novelty": "NEW",
        "editorial_novelty": "UNUSED",
        "freshness_class": "HIGH",
    })
    old = brain_repository.get_claim_metadata(old_claim)
    assert old["brain_status"] == "SUPERSEDED"
    assert old["superseded_by_claim_id"] == new_claim
