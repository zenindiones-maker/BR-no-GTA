from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from app.database.schema import initialize_schema
from app.database import harness_learning_repository as learning_repository
from app.database.telegram_conversation_repository import update_conversation_state
from app.services.continuous_intelligence_service import (
    DELTA_RESEARCH_CAPABILITY_ID,
    execute_gta6_delta_research_capability,
    gate_verified_gta6_claim,
)
from app.services.continuous_operation_policy_service import load_continuous_operation_policy
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_learning_service import HarnessEpisode, persist_episode
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.memory_plane_service import record_canonical_human_decision
from app.services.obsidian_memory_service import export_obsidian_memory_projection
from app.services.telegram_conversation_service import handle_telegram_conversation
from scripts import continuous_intelligence_cycle as continuous_cycle


GOAL = "goal-continuous-test"
SOURCE_URL = "https://www.rockstargames.com/VI/only-in-leonida"
QUERY = "What has Rockstar officially confirmed about Jason Duval's Army background and the Keys?"


def _route():
    return route_harness_request(
        HarnessRoutingRequest(
            intent="continuous GTA6 delta test",
            authorized_action="RESEARCH",
            domain="gta6",
            task_class="hermes:research",
            goal_id=GOAL,
            artifact_ref=SOURCE_URL,
            required_capability_id=DELTA_RESEARCH_CAPABILITY_ID,
            provider_required=False,
            fallback_allowed=False,
            learning_required=True,
            zero_cost_operation=True,
        )
    )


def _auth(route, suffix: str):
    return issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"capability:{DELTA_RESEARCH_CAPABILITY_ID}",
        harness_decision_id=f"decision-{suffix}",
        execution_id=f"execution-{suffix}",
        lineage={"routing_id": route.routing_id},
    )


def _observed_episode(episode_id: str):
    now = datetime.now(timezone.utc).isoformat()
    return persist_episode(HarnessEpisode(
        episode_id=episode_id,
        goal_id=GOAL,
        decision_id=f"decision-{episode_id}",
        execution_id=f"execution-{episode_id}",
        task_id="fact-check",
        agent_id="gta6-fact-check",
        capability_id="gta6.fact-check",
        domain="gta6",
        task_class="hermes:fact-check",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status="COMPLETED",
        actual_outcome={"observed": True, "success": True},
        outcome_evidence=(f"evidence:{episode_id}",),
        input_refs=(SOURCE_URL,),
        output_refs=(f"result:{episode_id}",),
        evidence_refs=(f"evidence:{episode_id}",),
    ))


def test_continuous_policy_is_event_driven_bounded_and_media_safe():
    policy = load_continuous_operation_policy()
    assert policy.cadence["gta6_delta_scan_seconds"] >= 6 * 60 * 60
    assert policy.resource_governance["max_tasks_per_mission"] <= 12
    assert policy.resource_governance["max_retries_per_task"] <= 3
    assert policy.resource_governance["max_reviewer_loops"] <= 3
    assert all(value is False for value in policy.safety.values())


def test_real_delta_contract_reuses_promoted_canonical_knowledge(monkeypatch):
    initialize_schema()
    excerpt = (
        "Jason grew up around grifters and crooks. "
        "After a stint in the Army trying to shake off his troubled teens, "
        "he found himself in the Keys doing what he knows best, working for local drug runners."
    )
    fingerprint = sha256(excerpt.encode("utf-8")).hexdigest()

    def fake_collect(query, *, execution_id, source_url):
        return {
            "status": "PASS",
            "execution_id": execution_id,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "official_source_count": 1,
            "secondary_source_count": 0,
            "source_errors": [],
            "submitted_source": {
                "resolution_status": "PASS",
                "url": source_url,
                "resolved_url": source_url,
                "source_name": "Rockstar Games GTA VI",
                "source_hierarchy": "OFFICIAL_PRIMARY",
                "content_excerpt": excerpt,
                "content_fingerprint": fingerprint,
                "content_sha256": fingerprint,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            "official_sources": [],
        }

    monkeypatch.setattr(
        "app.services.continuous_intelligence_service._collect_live",
        fake_collect,
    )

    route_a = _route()
    auth_a = _auth(route_a, "delta-a")
    first = execute_gta6_delta_research_capability(
        authorization=auth_a,
        routing_decision=route_a,
        payload={
            "query": QUERY,
            "subject": "Jason Duval",
            "source_url": SOURCE_URL,
            "goal_id": GOAL,
            "allow_delta_reuse": False,
        },
    )
    consume_harness_authorization(auth_a)
    assert first["status"] == "PASS"
    assert first["candidate_claims"]
    assert first["candidate_claims"][0]["source_type"] == "PRIMARY_SOURCE"
    assert first["candidate_claims"][0]["evidence_class"] == "OFFICIAL"

    episode = _observed_episode("episode-delta-knowledge")
    promoted = gate_verified_gta6_claim(
        candidate_claim=first["candidate_claims"][0],
        fact_check={"verdict": "SUPPORTED", "confidence": 1.0},
        source_episode_id=episode["episode_id"],
    )
    assert promoted["status"] == "PROMOTED"
    assert promoted["GTA6_KNOWLEDGE_PROMOTION_GATE"] == "PASS"

    route_b = _route()
    auth_b = _auth(route_b, "delta-b")
    second = execute_gta6_delta_research_capability(
        authorization=auth_b,
        routing_decision=route_b,
        payload={
            "query": "What does verified Rockstar material say about Jason's Army background and the Keys?",
            "subject": "Jason Duval",
            "source_url": SOURCE_URL,
            "goal_id": GOAL,
            "allow_delta_reuse": True,
        },
    )
    consume_harness_authorization(auth_b)
    assert second["status"] == "NO_MEANINGFUL_GTA6_DELTA"
    assert second["source_fetch_count"] == 0
    assert second["memory_hit_count"] > 0
    assert second["duplicate_research_avoided"] is True


def test_non_primary_claim_cannot_auto_promote_to_knowledge_brain():
    episode = _observed_episode("episode-community-claim")
    result = gate_verified_gta6_claim(
        candidate_claim={
            "subject": "Jason Duval",
            "claim_text": "A community post claims an unverified Jason detail.",
            "source_id": "community:example",
            "source_url": "https://example.invalid/community",
            "source_type": "COMMUNITY_OBSERVATION",
            "published_at": None,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "evidence_ref": "community:example:1",
            "evidence_class": "COMMUNITY_OBSERVATION",
            "status": "UNVERIFIED",
            "related_claims": [],
        },
        fact_check={"verdict": "SUPPORTED", "confidence": 1.0},
        source_episode_id=episode["episode_id"],
    )
    assert result["status"] == "HUMAN_REVIEW"
    assert result["knowledge"] is None
    assert result["memory_gate"]["memory"]["status"] == "CANDIDATE"


def test_obsidian_projection_exposes_objective_health_and_knowledge_map(tmp_path):
    manifest = export_obsidian_memory_projection(
        output_root=tmp_path / "obsidian-memory-export",
        system_state={
            "head": "a" * 40,
            "status": "CONTINUOUS_OPERATION_ACTIVE",
            "system_health": {
                "executions_total": 3,
                "executions_success": 3,
                "memory_hits": 2,
                "memory_misses": 1,
            },
            "active_gates": {"knowledge_promotion": "MEMORY_GATE_REQUIRED"},
            "evidence_refs": ["test:continuous"],
        },
        project_goals={"VIDEO-A": GOAL},
    )
    files = set(manifest["files"])
    assert "00-System/System-Health.md" in files
    assert "00-System/Active-Gates.md" in files
    assert "40-Knowledge/GTA6/Claims/Index.md" in files
    assert "40-Knowledge/GTA6/Characters/Index.md" in files
    assert "40-Knowledge/GTA6/Locations/Index.md" in files
    assert "40-Knowledge/GTA6/Mechanics/Index.md" in files
    assert "40-Knowledge/GTA6/Official-Sources/Index.md" in files
    assert "40-Knowledge/GTA6/Contradictions/Index.md" in files
    assert manifest["OBSIDIAN_CANONICAL_MEMORY"] == "NO"
    assert manifest["TERMUX_HEAVY_PROCESSING"] == "NO"


def test_obsidian_human_decision_is_recalled_by_telegram_without_provider():
    chat_id = 880042
    update_conversation_state(
        chat_id,
        active_goal_id=GOAL,
        active_artifact="script:8",
    )
    decision = record_canonical_human_decision(
        decision_type="USER_NOTE",
        source_surface="obsidian",
        source_ref="Inbox/voice-review.md",
        content="Não produzir nova voz antes da revisão e aprovação humana do roteiro.",
        evidence_refs=("obsidian-inbox:Inbox/voice-review.md:sha256:test",),
        goal_id=GOAL,
        task_id="script-human-review",
        artifact_ref="script:8",
        metadata={"target": "video-a"},
    )
    result = handle_telegram_conversation(
        "O que eu decidi sobre a voz?",
        telegram_chat_id=chat_id,
        telegram_message_id=880043,
        chat_handler=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("canonical memory recall must not use an external provider")
        ),
    )
    assert result["intent"] == "MEMORY_RECALL_REQUEST"
    assert result["plan"]["kind"] == "MEMORY_RECALL"
    assert result["canonical_result"]["provider_independent"] is True
    assert decision["decision_id"] in {
        item["decision_id"]
        for item in result["canonical_result"]["human_decisions"]
    }
    assert "Não produzir nova voz" in result["canonical_result"]["answer"]



def test_scheduled_entrypoint_contract_runs_main_without_checks_keyerror(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(continuous_cycle, "_is_due", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        continuous_cycle,
        "_failure_prevention",
        lambda: {
            "FAILURE_MEMORY_RETRIEVAL": "PASS",
            "FAILURE_RECURRENCE_PREVENTION": "PASS",
            "brain_semantic_task": "SKIPPED_KNOWN_UNCHANGED_PROVIDER_BLOCKER",
            "failure_memory_id": "memory-opencode-403-test",
        },
    )
    artifact_dir = tmp_path / "scheduled"
    upstream_root = tmp_path / "hermes-upstream"
    upstream_root.mkdir()
    monkeypatch.setattr(
        "sys.argv",
        [
            "continuous_intelligence_cycle.py",
            "--artifact-dir",
            str(artifact_dir),
            "--upstream-root",
            str(upstream_root),
            "--target-sha",
            "a" * 40,
            "--trigger-kind",
            "schedule",
            "--mode",
            "scheduled",
        ],
    )

    assert continuous_cycle.main() == 0
    output = capsys.readouterr().out
    assert "CONTINUOUS_OPERATION=PASS" in output
    assert "SCHEDULED_ENTRYPOINT_CONTRACT=PASS" in output
    report = __import__("json").loads(
        (artifact_dir / "continuous-cycle.json").read_text(encoding="utf-8")
    )
    assert report["checks"]["SCHEDULED_ENTRYPOINT_CONTRACT"] is True
    assert report["due"] == {
        "gta6": False,
        "daily": False,
        "improvement": False,
        "weekly": False,
    }



def test_improvement_observations_deduplicate_evidence_refs(monkeypatch, tmp_path):
    baseline = {
        "mission_id": "baseline-real-run",
        "research_elapsed_seconds": 1.0,
        "research": {
            "result": {
                "status": "PASS",
                "evidence_refs": ["evidence:baseline", "evidence:baseline"],
            }
        },
    }
    trial = {
        "mission_id": "candidate-real-run",
        "research_elapsed_seconds": 0.1,
        "research": {
            "result": {
                "status": "NO_MEANINGFUL_GTA6_DELTA",
                "evidence_refs": ["evidence:candidate", "evidence:candidate"],
            }
        },
    }
    monkeypatch.setattr(
        continuous_cycle,
        "_find_episode",
        lambda **_kwargs: {
            "episode_id": "episode-baseline-real",
            "evidence_refs": ["evidence:baseline", "evidence:baseline"],
        },
    )
    monkeypatch.setattr(
        continuous_cycle,
        "create_learning_candidate",
        lambda **_kwargs: {"candidate_id": "candidate-delta-reuse-test"},
    )
    monkeypatch.setattr(
        continuous_cycle,
        "_run_intelligence_mission",
        lambda **_kwargs: trial,
    )

    captured = {}

    def fake_evaluate(**kwargs):
        captured.update(kwargs)
        return {
            "decision": "PROMOTE",
            "evaluation_id": "evaluation-delta-reuse-test",
            "evaluation_mode": "OBSERVED",
            "baseline_metrics": kwargs["baseline_observation"]["metrics"],
            "candidate_metrics": kwargs["candidate_observation"]["metrics"],
        }

    monkeypatch.setattr(
        continuous_cycle,
        "evaluate_candidate_from_observed_results",
        fake_evaluate,
    )
    monkeypatch.setattr(
        continuous_cycle,
        "issue_harness_authorization",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        continuous_cycle,
        "promote_candidate",
        lambda **_kwargs: {"status": "PROMOTED"},
    )
    monkeypatch.setattr(
        continuous_cycle,
        "consume_harness_authorization",
        lambda *_args, **_kwargs: None,
    )

    candidate, evaluation, improvement = (
        continuous_cycle._create_and_test_improvement_candidate(
            baseline=baseline,
            topic={
                "query": QUERY,
                "subject": "Jason Duval",
                "source_url": SOURCE_URL,
            },
            upstream_root=tmp_path / "hermes",
            artifact_root=tmp_path / "artifacts",
            target_sha="a" * 40,
            regression_evidence_ref="regression:real",
        )
    )

    baseline_refs = captured["baseline_observation"]["evidence_refs"]
    candidate_refs = captured["candidate_observation"]["evidence_refs"]
    assert baseline_refs == list(dict.fromkeys(baseline_refs))
    assert candidate_refs == list(dict.fromkeys(candidate_refs))
    assert evaluation["decision"] == "PROMOTE"
    assert candidate["candidate_id"] == "candidate-delta-reuse-test"
    assert improvement["trial"]["mission_id"] == "candidate-real-run"



def test_zero_source_fetch_count_is_preserved_for_duplicate_research_gate():
    assert continuous_cycle._observed_source_fetch_count(
        {"source_fetch_count": 0}
    ) == 0
    assert continuous_cycle._observed_source_fetch_count(
        {"source_fetch_count": 1}
    ) == 1
    assert continuous_cycle._observed_source_fetch_count({}) == -1



def test_next_execution_changed_gate_is_strict_boolean():
    changed = continuous_cycle._next_execution_changed(
        {"status": "NO_MEANINGFUL_GTA6_DELTA"},
        {"active_delta_policy_memory_id": "memory-delta-reuse"},
    )
    assert changed is True
    assert isinstance(changed, bool)
    assert continuous_cycle._next_execution_changed(
        {"status": "PASS"},
        {"active_delta_policy_memory_id": "memory-delta-reuse"},
    ) is False
    assert continuous_cycle._next_execution_changed(
        {"status": "NO_MEANINGFUL_GTA6_DELTA"},
        {"active_delta_policy_memory_id": None},
    ) is False
