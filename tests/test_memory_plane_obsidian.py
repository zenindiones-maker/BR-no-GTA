from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database import harness_learning_repository as repository
from app.services.bounded_memory_context_service import build_bounded_memory_context
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_learning_service import HarnessEpisode, persist_episode, record_memory
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.memory_plane_service import (
    evaluate_memory_candidate,
    record_canonical_human_decision,
)
from app.services.obsidian_memory_service import (
    OBSIDIAN_INBOX_CAPABILITY_ID,
    execute_obsidian_inbox_capability,
    export_obsidian_memory_projection,
    parse_human_note,
)


GOAL = "goal-video-a-memory-test"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _episode(*, episode_id: str, status: str = "FAILED", error: str | None = "same failure"):
    now = _now()
    return HarnessEpisode(
        episode_id=episode_id,
        goal_id=GOAL,
        decision_id=f"decision-{episode_id}",
        execution_id=f"execution-{episode_id}",
        task_id="telegram-semantic-reasoning",
        agent_id="provider:opencode",
        capability_id="ai.reasoning.text",
        domain="ai",
        task_class="telegram-reasoning",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status=status,
        actual_outcome={"observed": True, "success": status == "COMPLETED"},
        outcome_evidence=(f"evidence:{episode_id}",),
        input_refs=("script:8",),
        output_refs=((f"output:{episode_id}",) if status == "COMPLETED" else ()),
        evidence_refs=(f"evidence:{episode_id}",),
        error=error,
        artifact_refs=("script:8",),
        lineage={"canonical_memory_plane": "HARNESS_LEARNING_PLANE"},
    )


def _candidate_for_episode(episode_id: str):
    for item in repository.list_memories(status="CANDIDATE", limit=100):
        if episode_id in (item.get("source_episode_ids") or ()):
            return item
    raise AssertionError("candidate not found")


def _memory_auth(memory_id: str, suffix: str):
    return issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"learning:memory:{memory_id}",
        harness_decision_id=f"decision-{suffix}",
        execution_id=f"execution-{suffix}",
    )


def test_episode_capture_creates_candidate_but_never_auto_promotes():
    persist_episode(_episode(
        episode_id="episode-memory-candidate",
        error="OpenCode free tier HTTP 403 before inference",
    ))
    candidate = _candidate_for_episode("episode-memory-candidate")
    assert candidate["status"] == "CANDIDATE"
    assert candidate["failure_pattern"] == "opencode_free_tier_403"
    assert candidate["metadata"]["evaluation_required"] is True
    assert candidate["metadata"]["canonical_auto_promotion"] is False
    assert repository.list_memories(
        status="ACTIVE",
        failure_pattern="opencode_free_tier_403",
        limit=20,
    ) == []


def test_memory_gate_promotes_then_supersedes_without_deleting_lineage():
    persist_episode(_episode(episode_id="episode-old", error="old observed failure"))
    old = record_memory(
        memory_type="PROCEDURAL",
        claim="old procedure",
        domain="telegram-control",
        task_class="provider-free-control",
        source_episode_ids=("episode-old",),
        evidence_refs=("evidence:old",),
        status="CANDIDATE",
        identity_payload={"memory": "old"},
    )
    old_active = evaluate_memory_candidate(
        memory_id=old["memory_id"],
        decision="PROMOTE",
        reason="observed baseline",
        evidence_refs=("evidence:old",),
        authorization=_memory_auth(old["memory_id"], "old"),
    )["memory"]
    persist_episode(_episode(episode_id="episode-new", error="new observed failure"))
    new = record_memory(
        memory_type="PROCEDURAL",
        claim="new corrected procedure",
        domain="telegram-control",
        task_class="provider-free-control",
        source_episode_ids=("episode-new",),
        evidence_refs=("evidence:new",),
        status="CANDIDATE",
        identity_payload={"memory": "new"},
    )
    promoted = evaluate_memory_candidate(
        memory_id=new["memory_id"],
        decision="SUPERSEDE",
        supersedes_memory_id=old_active["memory_id"],
        reason="new evidence contradicts the older operational procedure",
        evidence_refs=("evidence:new",),
        authorization=_memory_auth(new["memory_id"], "new"),
    )
    previous = repository.get_memory(old_active["memory_id"])
    assert previous["status"] == "SUPERSEDED"
    assert previous["metadata"]["superseded_by_memory_id"] == new["memory_id"]
    assert promoted["memory"]["status"] == "ACTIVE"
    assert promoted["memory"]["metadata"]["supersedes_memory_id"] == old_active["memory_id"]


def test_bounded_context_separates_human_failure_and_artifact_lineage():
    decision = record_canonical_human_decision(
        decision_type="REJECTION",
        source_surface="telegram",
        source_ref="telegram-turn:memory-test",
        content="não gostei desse resultado",
        evidence_refs=("telegram-turn:memory-test",),
        goal_id=GOAL,
        task_id="telegram-semantic-reasoning",
        capability_id="ai.reasoning.text",
        artifact_ref="script:8",
    )
    persisted = persist_episode(_episode(
        episode_id="episode-bounded",
        error="OpenCode free tier HTTP 403 before inference",
    ))
    candidate = _candidate_for_episode(persisted["episode_id"])
    evaluate_memory_candidate(
        memory_id=candidate["memory_id"],
        decision="PROMOTE",
        reason="observed repeatable provider failure",
        evidence_refs=("evidence:episode-bounded",),
        authorization=_memory_auth(candidate["memory_id"], "bounded"),
    )

    context = build_bounded_memory_context(
        goal_id=GOAL,
        domain="ai",
        task_class="telegram-reasoning",
        capability_id="ai.reasoning.text",
        agent_id="provider:opencode",
        artifact_ref="script:8",
        failure_pattern="opencode_free_tier_403",
        intent="semantic reasoning",
    ).to_dict()
    assert context["used_bytes"] <= context["max_bytes"]
    assert decision["decision_id"] in {
        item["decision_id"] for item in context["conversation_memory"]
    }
    assert candidate["memory_id"] in {
        item["memory_id"] for item in context["operational_memory"]
    }
    assert persisted["episode_id"] in {
        item["episode_id"] for item in context["artifact_lineage_memory"]
    }


def test_routing_retrieves_bounded_memory_before_execution():
    route = route_harness_request(
        HarnessRoutingRequest(
            intent="ingest Obsidian human note",
            authorized_action="EXECUTION",
            domain="human-memory",
            task_class="obsidian-human-note",
            goal_id=GOAL,
            artifact_ref="script:8",
            required_capability_id=OBSIDIAN_INBOX_CAPABILITY_ID,
            provider_required=False,
            fallback_allowed=False,
            learning_required=True,
        )
    )
    learning = route.policy_metadata["learning_context"]
    assert learning["MEMORY_RETRIEVE_BEFORE_EXECUTION"] == "PASS"
    assert learning["BOUNDED_MEMORY_CONTEXT"] == "PASS"
    assert route.policy_metadata["memory_retrieve_before_execution"] is True


def test_obsidian_inbox_creates_shared_human_decision_and_gated_candidate():
    note = """---
type: human_note
target: video-a
---

Não produzir nova voz antes da revisão do roteiro.
"""
    parsed = parse_human_note(note)
    assert parsed["target"] == "video-a"

    route = route_harness_request(
        HarnessRoutingRequest(
            intent="ingest bounded Obsidian note",
            authorized_action="EXECUTION",
            domain="human-memory",
            task_class="obsidian-human-note",
            goal_id=GOAL,
            artifact_ref="script:8",
            required_capability_id=OBSIDIAN_INBOX_CAPABILITY_ID,
            provider_required=False,
            fallback_allowed=False,
            learning_required=True,
        )
    )
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{OBSIDIAN_INBOX_CAPABILITY_ID}",
        harness_decision_id="decision-obsidian-test",
        execution_id="execution-obsidian-test",
    )
    result = execute_obsidian_inbox_capability(
        authorization=auth,
        routing_decision=route,
        payload={
            "note_text": note,
            "source_ref": "Inbox/voice-feedback.md",
            "goal_id": GOAL,
            "task_id": "script-human-review",
            "artifact_ref": "script:8",
        },
    )
    assert result["OBSIDIAN_NOTE_INGESTED"] == "PASS"
    assert result["MEMORY_CANDIDATE_CREATED"] == "PASS"
    assert result["CANONICAL_AUTO_PROMOTION"] == "NO"
    assert result["HARNESS_EVALUATION_REQUIRED"] == "PASS"
    assert result["memory_candidate"]["status"] == "CANDIDATE"
    decisions = repository.list_canonical_human_decisions(goal_id=GOAL, limit=10)
    assert result["canonical_human_decision"]["decision_id"] in {
        item["decision_id"] for item in decisions
    }


def test_obsidian_export_is_projection_only_and_refuses_android_vault(tmp_path):
    record_canonical_human_decision(
        decision_type="INSTRUCTION",
        source_surface="obsidian",
        source_ref="Inbox/state.md",
        content="Preserve current review gate.",
        evidence_refs=("obsidian:Inbox/state.md",),
        goal_id=GOAL,
    )
    manifest = export_obsidian_memory_projection(
        output_root=tmp_path / "obsidian-memory-export",
        system_state={
            "head": "a" * 40,
            "status": "OBSERVED",
            "evidence_refs": ["test:evidence"],
        },
        project_goals={"VIDEO-A": GOAL},
    )
    assert manifest["OBSIDIAN_CANONICAL_MEMORY"] == "NO"
    assert manifest["TERMUX_HEAVY_PROCESSING"] == "NO"
    assert "00-System/Current-State.md" in manifest["files"]
    assert "10-Human-Decisions/VIDEO-A.md" in manifest["files"]
    with pytest.raises(PermissionError):
        export_obsidian_memory_projection(
            output_root=Path("/tmp/storage/shared/Documents/Obsidian/BR-no-GTA-Vault"),
            system_state={},
            project_goals={},
        )
