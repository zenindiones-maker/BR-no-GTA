from __future__ import annotations

import pytest

from app.database import harness_learning_repository as repository
from app.services.harness_incident_replay_service import (
    IncidentReplayCase,
    execute_selected_incident_replays,
    persist_incident_replay_case,
    retrieve_relevant_incident_replays,
)
from app.services.harness_learning_service import HarnessEpisode, persist_episode


def _episode(episode_id: str) -> HarnessEpisode:
    return HarnessEpisode(
        episode_id=episode_id,
        goal_id="goal-replay",
        decision_id="decision-replay",
        execution_id=f"exec-{episode_id}",
        task_id=f"task-{episode_id}",
        agent_id="replay-source-agent",
        capability_id="telegram.semantic.reasoning",
        skill_id=None,
        skill_version=None,
        provider="native",
        domain="telegram",
        task_class="telegram_semantic_reasoning",
        input_refs=(f"input:{episode_id}",),
        output_refs=(f"output:{episode_id}",),
        evidence_refs=(f"evidence:{episode_id}",),
        tool_calls=(),
        routing_decision={"selected": "replay-source-agent"},
        started_at="2026-09-30T00:00:00+00:00",
        finished_at="2026-09-30T00:00:01+00:00",
        duration_seconds=1.0,
        status="COMPLETED",
        actual_outcome={"observed": True, "success": True},
        outcome_evidence=(f"artifact:{episode_id}:sha256",),
        error=None,
        retry_count=0,
        human_intervention=False,
        qa_results={"status": "PASS"},
        cost=0.0,
        latency_seconds=1.0,
        commit_ref="commit:test",
        run_ref="run:test",
        artifact_refs=(f"artifact:{episode_id}",),
        source_versions={"runtime": "v1"},
    )


def _case(*, episode_id: str, incident_id: str = "telegram-real") -> IncidentReplayCase:
    return IncidentReplayCase.create(
        incident_id=incident_id,
        title="Telegram semantic request replay",
        task_class="telegram_semantic_reasoning",
        domain="telegram",
        incident_class="DURABILITY",
        original_symptom="semantic request lost after transient provider failure",
        root_cause="request was not durably rebound before semantic execution",
        source_episode_ids=(episode_id,),
        source_failure_memory_ids=(),
        evidence_refs=(f"artifact:runtime:{episode_id}",),
        affected_capability_ids=("telegram.semantic.reasoning",),
        affected_agent_ids=("telegram-gateway",),
        affected_provider_ids=("provider-a",),
        affected_skill_ids=(),
        minimal_reproducer="fixture:telegram:request-107",
        fixture_refs=("fixture:telegram:request-107",),
        preconditions=("document already materialized",),
        expected_behavior="same durable semantic request resumes without human resend",
        forbidden_behavior=("human resend required",),
        hard_invariants=("HUMAN_RETRY_REQUIRED=0",),
        verification_commands_or_eval_refs=("pytest:telegram-durable-semantic",),
        known_good_revision="known-good",
        fixed_revision="fixed",
        created_at="2026-09-30T00:00:00+00:00",
        last_verified_at="2026-09-30T00:00:00+00:00",
        status="ACTIVE",
        confidence=0.99,
        changed_surfaces=("scripts/telegram_harness_gateway_v2.py",),
    )


def test_incident_replay_persists_in_existing_harness_memories():
    persist_episode(_episode("replay-source-real"))
    case = _case(episode_id="replay-source-real")
    persisted = persist_incident_replay_case(case)

    assert persisted["memory_type"] == "INCIDENT_REPLAY"
    durable = repository.get_memory(persisted["memory_id"])
    assert durable is not None
    assert durable["metadata"]["replay_case"]["replay_case_id"] == case.replay_case_id
    assert durable["source_episode_ids"] == ["replay-source-real"]


def test_incident_replay_requires_observed_source_episode():
    case = _case(episode_id="does-not-exist", incident_id="missing-source")
    with pytest.raises(ValueError, match="source episode not found"):
        persist_incident_replay_case(case)


def test_selective_retrieval_persists_selection_reason():
    persist_episode(_episode("replay-selection-source"))
    relevant = persist_incident_replay_case(
        _case(episode_id="replay-selection-source", incident_id="relevant")
    )

    selected = retrieve_relevant_incident_replays(
        domain="telegram",
        task_class="telegram_semantic_reasoning",
        capability_ids=("telegram.semantic.reasoning",),
        provider_ids=("provider-a",),
        failure_fingerprint=None,
        changed_surfaces=("scripts/telegram_harness_gateway_v2.py",),
        risk_class="HIGH",
    )

    assert [item["memory_id"] for item in selected] == [relevant["memory_id"]]
    assert "changed_surface" in selected[0]["selection_reasons"]
    reread = repository.get_memory(relevant["memory_id"])
    history = reread["metadata"]["selection_history"]
    assert history[-1]["selection_reasons"]
    assert history[-1]["risk_class"] == "HIGH"


def test_irrelevant_replay_is_not_executed(monkeypatch):
    memories = [
        {
            "memory_id": "m-relevant",
            "domain": "telegram",
            "task_class": "telegram_semantic_reasoning",
            "confidence": 1.0,
            "failure_pattern": "DURABILITY:abc",
            "metadata": {"replay_case": {
                "replay_case_id": "r-relevant",
                "domain": "telegram",
                "task_class": "telegram_semantic_reasoning",
                "affected_capability_ids": ["telegram.semantic.reasoning"],
                "affected_provider_ids": [],
                "changed_surfaces": ["scripts/telegram_harness_gateway_v2.py"],
                "fingerprint": "abc",
                "minimal_reproducer": "fixture:relevant",
                "verification_commands_or_eval_refs": ["eval:relevant"],
            }},
        },
        {
            "memory_id": "m-irrelevant",
            "domain": "video",
            "task_class": "video_render",
            "confidence": 1.0,
            "failure_pattern": "ENCODE:def",
            "metadata": {"replay_case": {
                "replay_case_id": "r-irrelevant",
                "domain": "video",
                "task_class": "video_render",
                "affected_capability_ids": ["video.render"],
                "affected_provider_ids": [],
                "changed_surfaces": ["app/video/render.py"],
                "fingerprint": "def",
                "minimal_reproducer": "fixture:irrelevant",
                "verification_commands_or_eval_refs": ["eval:irrelevant"],
            }},
        },
    ]
    monkeypatch.setattr(
        repository,
        "list_memories",
        lambda **kwargs: memories,
    )
    monkeypatch.setattr(
        repository,
        "add_memory_selection_observation",
        lambda memory_id, observation: next(
            item for item in memories if item["memory_id"] == memory_id
        ),
    )

    selected = retrieve_relevant_incident_replays(
        domain="telegram",
        task_class="telegram_semantic_reasoning",
        capability_ids=("telegram.semantic.reasoning",),
        provider_ids=(),
        failure_fingerprint="abc",
        changed_surfaces=("scripts/telegram_harness_gateway_v2.py",),
        risk_class="HIGH",
    )
    executed: list[str] = []
    batch = execute_selected_incident_replays(
        selected_memories=selected,
        executor=lambda request: (
            executed.append(request["replay_case_id"])
            or {"status": "PASS", "evidence_refs": ("artifact:replay-pass",)}
        ),
    )

    assert executed == ["r-relevant"]
    assert batch["gate"] == "PASS"
    assert batch["REPLAY_RELEVANCE_SELECTION"] == "PASS"
    assert batch["IRRELEVANT_REPLAY_CASE_NOT_EXECUTED"] == "PASS"


def test_incident_replay_extension_requires_no_parallel_database_or_schema():
    persist_episode(_episode("replay-schema-source"))
    persisted = persist_incident_replay_case(
        _case(episode_id="replay-schema-source", incident_id="schema-compat")
    )
    rows = repository.list_memories(memory_type="INCIDENT_REPLAY", status="ACTIVE")
    assert persisted["memory_id"] in {row["memory_id"] for row in rows}
