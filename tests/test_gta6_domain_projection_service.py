from __future__ import annotations

import json

from app.database import harness_learning_repository
from app.services import gta6_domain_projection_service as service


def _empty(monkeypatch):
    monkeypatch.setattr(service, "list_research_items", lambda: [])
    monkeypatch.setattr(service, "list_ideas", lambda: [])
    monkeypatch.setattr(service, "list_editorial_evaluations", lambda: [])
    monkeypatch.setattr(service, "list_queue_items", lambda: [])
    monkeypatch.setattr(service, "list_active_queue_items", lambda: [])
    monkeypatch.setattr(service, "list_scripts", lambda: [])
    monkeypatch.setattr(service, "list_videos", lambda: [])
    monkeypatch.setattr(service, "list_youtube_publications", lambda: [])
    monkeypatch.setattr(service, "list_render_jobs", lambda: [])
    monkeypatch.setattr(
        service,
        "get_gta6_monitor_state",
        lambda url: None,
    )
    monkeypatch.setattr(
        service,
        "retrieve_gta6_knowledge",
        lambda **kwargs: {
            "retrieval_mode": "TEST",
            "knowledge_units": [],
        },
    )
    monkeypatch.setattr(
        service,
        "load_operational_learning_context",
        lambda **kwargs: {
            "retrieved_memory_ids": [],
            "retrieved_failure_memory_ids": [],
            "retrieved_human_feedback_ids": [],
            "retrieved_human_decision_ids": [],
            "learning_participated": False,
        },
    )
    monkeypatch.setattr(
        harness_learning_repository,
        "list_episodes",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        harness_learning_repository,
        "list_memories",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        harness_learning_repository,
        "list_human_corrections",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        harness_learning_repository,
        "list_canonical_human_decisions",
        lambda **kwargs: [],
    )


def test_projection_schema_summary_rich_state_and_deterministic_hash(
    monkeypatch,
):
    _empty(monkeypatch)
    monkeypatch.setattr(
        service,
        "list_research_items",
        lambda: [{
            "id": 1,
            "title": "Official Extended Look",
            "published_at": "2026-08-27T12:00:00+00:00",
            "collected_at": "2026-08-27T12:05:00+00:00",
        }],
    )
    monkeypatch.setattr(
        service,
        "list_ideas",
        lambda: [{
            "id": 9,
            "title": "Extended Look findings",
            "status": "approved",
        }],
    )
    queue_item = {
        "id": 2,
        "idea_id": 9,
        "priority_score": 99.0,
        "priority": "HIGH",
        "status": "queued",
        "updated_at": "2026-08-27T12:10:00+00:00",
    }
    monkeypatch.setattr(
        service,
        "list_queue_items",
        lambda: [dict(queue_item)],
    )
    monkeypatch.setattr(
        service,
        "list_active_queue_items",
        lambda: [dict(queue_item)],
    )
    monkeypatch.setattr(
        service,
        "list_editorial_evaluations",
        lambda: [{
            "id": 3,
            "idea_id": 9,
            "decision": "approved",
            "novelty": 0.92,
            "created_at": "2026-08-27T12:09:00+00:00",
        }],
    )
    monkeypatch.setattr(
        service,
        "list_scripts",
        lambda: [{
            "id": 4,
            "idea_id": 9,
            "version": 1,
            "status": "approved",
            "updated_at": "2026-08-27T12:11:00+00:00",
        }],
    )
    monkeypatch.setattr(
        service,
        "retrieve_gta6_knowledge",
        lambda **kwargs: {
            "retrieval_mode": "TEST",
            "knowledge_units": [{
                "claim_id": 11,
                "claim": "Rockstar showed a bounded official scene.",
                "claim_type": "official",
                "status": "active",
                "brain_status": "VERIFIED",
                "confidence": 9.0,
                "source_id": "rockstar",
                "source_type": "OFFICIAL",
                "authority_class": "OFFICIAL",
                "published_at": "2026-08-27T12:00:00+00:00",
                "observed_at": "2026-08-27T12:05:00+00:00",
                "evidence_ref": "evidence:11",
                "evidence_class": "PRIMARY",
                "novelty": {
                    "world": "NEW",
                    "knowledge": "NEW",
                    "editorial": "UNUSED",
                },
                "scores": {"freshness": 1.0, "hybrid": 0.9},
            }],
        },
    )

    first = service.build_gta6_domain_projection(
        mission_id="mission-1",
        task_id="task-1",
        goal_id="goal-1",
    )
    second = service.build_gta6_domain_projection(
        mission_id="mission-1",
        task_id="task-1",
        goal_id="goal-1",
    )

    assert first == second
    assert first["schema"] == "GTA6DomainProjection/v1"
    assert first["projection_owner"] == "DEEPSEEK_HARNESS_BOUNDARY"
    assert first["brain_projection_authority"] == "NONE"
    assert first["summary"]["research_count"] == 1
    assert first["summary"]["active_queue_count"] == 1
    assert (
        first["research"]["recent_high_value_claims"][0]["claim_id"]
        == 11
    )
    assert (
        first["editorial"]["active_editorial_items"][0]["idea_id"]
        == 9
    )
    assert first["production"]["script_status"] == "approved"
    assert "evidence:11" in first["evidence_refs"]
    assert len(first["content_sha256"]) == 64
    raw = json.dumps(first, ensure_ascii=False).encode("utf-8")
    assert len(raw) <= service.MAX_PROJECTION_BYTES


def test_projection_learning_feedback_is_bounded_and_relevant(monkeypatch):
    _empty(monkeypatch)
    monkeypatch.setattr(
        service,
        "load_operational_learning_context",
        lambda **kwargs: {
            "retrieved_memory_ids": [f"mem-{i}" for i in range(10)],
            "retrieved_failure_memory_ids": [
                f"fail-{i}" for i in range(10)
            ],
            "retrieved_human_feedback_ids": [
                f"corr-{i}" for i in range(10)
            ],
            "retrieved_human_decision_ids": [],
            "learning_participated": True,
        },
    )
    monkeypatch.setattr(
        harness_learning_repository,
        "list_episodes",
        lambda **kwargs: [
            {
                "episode_id": f"ep-{i}",
                "goal_id": "goal-1",
                "task_id": "task-1",
                "agent_id": "gta6-brain",
                "decision_id": f"d-{i}",
                "status": "COMPLETED",
                "created_at": (
                    f"2026-09-{20+i:02d}T00:00:00+00:00"
                ),
                "finished_at": (
                    f"2026-09-{20+i:02d}T00:00:01+00:00"
                ),
                "actual_outcome": {
                    "success": True,
                    "DOMAIN_DECISION": {
                        "action": "RESEARCH",
                        "reason": f"reason {i}",
                        "priority": "HIGH",
                        "confidence": 0.8,
                    },
                    "DOMAIN_PROJECTION": {
                        "projection_ref": f"projection:{i}",
                        "content_sha256": f"{i:064x}",
                    },
                },
                "evidence_refs": [f"episode-evidence:{i}"],
            }
            for i in range(8)
        ],
    )
    monkeypatch.setattr(
        harness_learning_repository,
        "list_memories",
        lambda **kwargs: [
            {
                "memory_id": f"failure-{i}",
                "failure_pattern": "DOMAIN_QUALITY",
                "claim": f"failure memory {i}",
                "confidence": 0.9,
                "source_episode_ids": [f"ep-{i}"],
                "evidence_refs": [f"failure-evidence:{i}"],
                "created_at": "2026-09-20T00:00:00+00:00",
                "last_verified_at": "2026-09-25T00:00:00+00:00",
            }
            for i in range(8)
        ],
    )
    monkeypatch.setattr(
        harness_learning_repository,
        "list_human_corrections",
        lambda **kwargs: [
            {
                "correction_id": f"corr-{i}",
                "goal_id": "goal-1" if i < 6 else "other-goal",
                "task_id": None,
                "affected_agent": "gta6-brain",
                "affected_capability": "gta6.brain.decide",
                "desired_behavior": f"prefer novelty {i}",
                "undesired_behavior": "repeat old topic",
                "scope": "LOCAL",
                "status": "CANDIDATE",
                "created_at": (
                    f"2026-09-{10+i:02d}T00:00:00+00:00"
                ),
                "evidence_refs": [f"human:{i}"],
            }
            for i in range(8)
        ],
    )

    projection = service.build_gta6_domain_projection(
        mission_id="mission-1",
        task_id="task-1",
        goal_id="goal-1",
    )
    feedback = projection["decision_feedback"]
    assert len(feedback["recent_brain_decisions"]) == 4
    assert len(feedback["relevant_failure_memories"]) == 4
    assert len(feedback["relevant_human_corrections"]) == 3
    assert all(
        "other-goal" not in json.dumps(item)
        for item in feedback["relevant_human_corrections"]
    )
    assert "provider_id" not in json.dumps(feedback).lower()
    assert "model_id" not in json.dumps(feedback).lower()


def test_projection_preserves_unknown_instead_of_inventing_zero(monkeypatch):
    _empty(monkeypatch)
    projection = service.build_gta6_domain_projection(
        mission_id="mission-1",
        task_id="task-1",
        goal_id="goal-1",
    )
    assert projection["research"]["actionable_gap_count"] == "UNKNOWN"
    assert projection["production"]["voice_status"] == "UNKNOWN"
    assert projection["production"]["pronunciation_gate"] == "UNKNOWN"
    assert projection["review"]["pending_human_review"] == "UNKNOWN"



def test_projection_normalizes_sqlite_and_offset_timestamps(monkeypatch):
    _empty(monkeypatch)
    monkeypatch.setattr(
        service,
        "list_research_items",
        lambda: [{
            "id": 1,
            "title": "SQLite timestamp",
            "published_at": None,
            "collected_at": "2026-09-27 17:00:00",
        }],
    )
    monkeypatch.setattr(
        harness_learning_repository,
        "list_episodes",
        lambda **kwargs: [{
            "episode_id": "episode-aware",
            "goal_id": "goal-1",
            "task_id": "task-1",
            "agent_id": "gta6-brain",
            "decision_id": "decision-aware",
            "status": "COMPLETED",
            "created_at": "2026-09-27 17:01:00",
            "finished_at": "2026-09-27T17:01:01+00:00",
            "actual_outcome": {"success": True},
            "evidence_refs": [],
        }],
    )

    projection = service.build_gta6_domain_projection(
        mission_id="mission-1",
        task_id="task-1",
        goal_id="goal-1",
    )

    assert projection["observed_at"] == "2026-09-27T17:01:01+00:00"
    assert len(projection["content_sha256"]) == 64
