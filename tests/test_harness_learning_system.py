from __future__ import annotations

from pathlib import Path
import json

import pytest

from app.database import harness_learning_repository as repository
from app.database.connection import get_connection
from app.services.global_capability_registry_base import (
    AVAILABLE,
    FUNCTIONAL,
    CapabilityRecord,
    GlobalCapabilityRegistry,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_learning_service import (
    HarnessEpisode,
    competence_metrics,
    contradict_memory,
    create_improvement_mission,
    create_learning_candidate,
    evaluate_candidate,
    mark_stale_memories_for_version_change,
    persist_episode,
    promote_candidate,
    record_human_correction,
    record_memory,
    register_policy_version,
    register_skill_version,
    retrieve_agent_competence,
    retrieve_known_failure_patterns,
    retrieve_relevant_human_feedback,
    retrieve_relevant_memory,
    route_harness_request_with_learning,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request


def _episode(*, episode_id: str, execution_id: str, capability_id: str = "learning.candidate",
             agent_id: str = "learning-engineer", skill_version: str = "v2",
             status: str = "COMPLETED", retry_count: int = 0,
             human_intervention: bool = False, error: dict | str | None = None,
             observed: bool = True) -> HarnessEpisode:
    return HarnessEpisode(
        episode_id=episode_id,
        goal_id="goal-learning",
        decision_id="decision-learning",
        execution_id=execution_id,
        task_id=f"task-{episode_id}",
        agent_id=agent_id,
        capability_id=capability_id,
        skill_id="learning.artifact-integrity",
        skill_version=skill_version,
        provider="native",
        domain="system-learning",
        task_class="artifact-integrity",
        input_refs=(f"input:{episode_id}",),
        output_refs=(f"output:{episode_id}",),
        evidence_refs=(f"evidence:{episode_id}",),
        tool_calls=({"tool": "pytest", "status": "observed"},),
        routing_decision={"routing_id": f"route-{episode_id}"},
        started_at="2026-09-18T00:00:00+00:00",
        finished_at="2026-09-18T00:00:01+00:00",
        duration_seconds=1.0,
        status=status,
        actual_outcome={
            "observed": observed,
            "success": status == "COMPLETED",
            **({"agent_report": "done"} if observed else {}),
        },
        outcome_evidence=(f"artifact:{episode_id}:sha256",),
        error=error,
        retry_count=retry_count,
        human_intervention=human_intervention,
        qa_results={"status": "PASS" if status == "COMPLETED" else "FAIL"},
        latency_seconds=1.0,
        cost=0.0,
        commit_ref="commit:test",
        run_ref="run:test",
        artifact_refs=(f"artifact:{episode_id}",),
        source_versions={"procedure": skill_version},
    )


def _candidate() -> dict:
    persist_episode(_episode(episode_id="source-a", execution_id="exec-source-a"))
    return create_learning_candidate(
        candidate_type="SKILL_UPDATE",
        hypothesis="preflight validation removes avoidable retry without reducing quality",
        domain="system-learning",
        task_class="artifact-integrity",
        source_episode_ids=("source-a",),
        evidence_refs=("artifact:source-a:sha256",),
        target_agent_id="learning-engineer",
        target_capability_id="learning.candidate",
        target_skill_id="learning.artifact-integrity",
        baseline_version="v1",
        candidate_version="v2",
        contradiction_check={"status": "NO_CONTRADICTION_FOUND"},
    )


def _metrics(*, retry_rate: float, human_rate: float, failure_recurrence: float,
             success: float = 1.0, quality: float = 1.0, latency: float = 1.0) -> dict:
    return {
        "task_success_rate": success,
        "quality": quality,
        "human_correction_rate": human_rate,
        "retry_rate": retry_rate,
        "failure_recurrence": failure_recurrence,
        "latency_seconds": latency,
        "cost": 0.0,
        "policy_violations": 0.0,
    }


def _registry() -> GlobalCapabilityRegistry:
    def record(capability_id: str, agent_id: str, skill_id: str) -> CapabilityRecord:
        return CapabilityRecord(
            capability_id=capability_id,
            capability_type="CAPABILITY",
            domain="system-learning",
            implementation="artifact integrity learning proof executor",
            input_contract="controlled task",
            output_contract="observed artifact",
            requirements=("Harness authorization",),
            maturity=FUNCTIONAL,
            availability=AVAILABLE,
            allowed_actions=("EXECUTION",),
            policy_tags=("learning", "artifact", "integrity"),
            security_boundary="DeepSeek Harness sole authority; no publication authority",
            cost_class="FREE_NO_BILLING",
            quota_class="LOCAL",
            latency_class="LOW",
            quality_class="DETERMINISTIC",
            evidence_contract="observed artifact sha256",
            fallback_eligibility=False,
            executor_binding=f"proof.{capability_id}",
            version="1",
            agent_id=agent_id,
            skill_id=skill_id,
        )
    return GlobalCapabilityRegistry((
        record("learning.baseline", "baseline-agent", "learning.artifact-integrity"),
        record("learning.candidate", "candidate-agent", "learning.artifact-integrity"),
    ))


def test_episode_persistence_trace_and_observed_outcome():
    episode = _episode(episode_id="episode-1", execution_id="exec-1")
    persisted = persist_episode(episode)
    assert persisted["actual_outcome"]["observed"] is True
    assert persisted["tool_calls"][0]["tool"] == "pytest"
    assert persisted["outcome_evidence"] == ["artifact:episode-1:sha256"]
    assert repository.get_episode("episode-1")["goal_id"] == "goal-learning"


def test_harness_episode_error_json_serialization_round_trip_and_legacy_text():
    structured_error = {
        "failure_class": "rate_limited",
        "http_status": 429,
        "retryable": True,
        "details": {"provider": "nvidia_nim"},
    }
    persisted = persist_episode(_episode(
        episode_id="episode-structured-error",
        execution_id="exec-structured-error",
        status="FAILED",
        observed=False,
        error=structured_error,
    ))
    assert persisted["error"] == structured_error
    assert repository.get_episode("episode-structured-error")["error"] == structured_error

    connection = get_connection()
    try:
        raw = connection.execute(
            "SELECT error FROM harness_episodes WHERE episode_id = ?",
            ("episode-structured-error",),
        ).fetchone()["error"]
    finally:
        connection.close()
    assert json.loads(raw) == structured_error

    none_error = persist_episode(_episode(
        episode_id="episode-none-error",
        execution_id="exec-none-error",
    ))
    assert none_error["error"] is None

    connection = get_connection()
    try:
        connection.execute(
            "UPDATE harness_episodes SET error = ? WHERE episode_id = ?",
            ("legacy plain-text failure", "episode-structured-error"),
        )
        connection.commit()
    finally:
        connection.close()
    assert (
        repository.get_episode("episode-structured-error")["error"]
        == "legacy plain-text failure"
    )


def test_agent_self_report_is_not_an_observed_outcome():
    with pytest.raises(ValueError, match="observed outcome"):
        _episode(episode_id="self-report", execution_id="exec-report", observed=False)


def test_duplicate_episode_prevention_is_idempotent():
    first = persist_episode(_episode(episode_id="episode-dup", execution_id="exec-dup"))
    second = persist_episode(_episode(episode_id="episode-dup", execution_id="exec-dup"))
    rows = repository.list_episodes(task_class="artifact-integrity")
    assert first["episode_id"] == second["episode_id"]
    assert len([row for row in rows if row["episode_id"] == "episode-dup"]) == 1


@pytest.mark.parametrize("memory_type", ["EPISODIC", "SEMANTIC", "PROCEDURAL", "FAILURE", "HUMAN_FEEDBACK", "COMPETENCE"])
def test_memory_types_are_provenanced_and_retrievable(memory_type: str):
    persist_episode(_episode(episode_id=f"episode-{memory_type}", execution_id=f"exec-{memory_type}"))
    memory = record_memory(
        memory_type=memory_type,
        claim=f"validated {memory_type.lower()} lesson",
        domain="system-learning",
        task_class="artifact-integrity",
        source_episode_ids=(f"episode-{memory_type}",),
        evidence_refs=(f"evidence:{memory_type}",),
        capability_id="learning.candidate",
        source_versions={"skill": "v2"},
        support_count=2,
        confidence=0.8,
        status="ACTIVE",
    )
    retrieved = retrieve_relevant_memory(
        goal="goal-learning",
        domain="system-learning",
        task_class="artifact-integrity",
        capability="learning.candidate",
    )
    assert memory["memory_id"] in {item["memory_id"] for item in retrieved}
    assert memory["source_episode_ids"] == [f"episode-{memory_type}"]


def test_memory_stales_when_source_version_changes():
    persist_episode(_episode(episode_id="episode-stale", execution_id="exec-stale"))
    memory = record_memory(
        memory_type="PROCEDURAL",
        claim="procedure v1 is valid",
        domain="system-learning",
        task_class="artifact-integrity",
        source_episode_ids=("episode-stale",),
        evidence_refs=("evidence:stale",),
        source_versions={"procedure": "v1"},
        status="ACTIVE",
    )
    stale = mark_stale_memories_for_version_change(current_versions={"procedure": "v2"}, domain="system-learning")
    assert memory["memory_id"] in stale
    assert memory["memory_id"] not in {
        item["memory_id"] for item in retrieve_relevant_memory(
            goal="goal-learning", domain="system-learning", task_class="artifact-integrity"
        )
    }


def test_contradicted_memory_is_excluded_from_active_retrieval():
    persist_episode(_episode(episode_id="episode-contradict", execution_id="exec-contradict"))
    memory = record_memory(
        memory_type="SEMANTIC",
        claim="candidate claim",
        domain="system-learning",
        task_class="artifact-integrity",
        source_episode_ids=("episode-contradict",),
        evidence_refs=("evidence:old",),
        status="ACTIVE",
    )
    contradict_memory(memory["memory_id"], evidence_ref="evidence:new")
    active = retrieve_relevant_memory(goal="goal-learning", domain="system-learning", task_class="artifact-integrity")
    assert memory["memory_id"] not in {item["memory_id"] for item in active}


def test_human_feedback_is_structured_and_not_global_by_default():
    correction = record_human_correction(
        context="render transport retry",
        undesired_behavior="retry without preflight",
        desired_behavior="validate before execution",
        evidence_refs=("telegram:human-correction:1",),
        goal_id="goal-learning",
        task_id="task-learning",
        affected_agent="learning-engineer",
        affected_capability="learning.candidate",
        affected_skill="learning.artifact-integrity",
    )
    assert correction["scope"] == "LOCAL"
    found = retrieve_relevant_human_feedback(capability="learning.candidate")
    assert correction["correction_id"] in {item["correction_id"] for item in found}


def test_competence_requires_multiple_observed_cases_before_active():
    persist_episode(_episode(episode_id="competence-1", execution_id="exec-competence-1"))
    first = retrieve_agent_competence(
        domain="system-learning", task_class="artifact-integrity", capability_id="learning.candidate"
    )[0]
    assert first["evidence_sufficient"] is False
    persist_episode(_episode(episode_id="competence-2", execution_id="exec-competence-2"))
    second = retrieve_agent_competence(
        domain="system-learning", task_class="artifact-integrity", capability_id="learning.candidate"
    )[0]
    assert second["tested_cases"] == 2
    assert second["status"] == "ACTIVE"
    assert second["success_rate"] == 1.0


def test_competence_metrics_capture_human_intervention_retry_and_failure():
    persist_episode(_episode(
        episode_id="metric-success", execution_id="exec-metric-success",
        capability_id="learning.baseline", agent_id="baseline-agent", skill_version="v1",
        retry_count=1, human_intervention=True,
    ))
    persist_episode(_episode(
        episode_id="metric-failure", execution_id="exec-metric-failure",
        capability_id="learning.baseline", agent_id="baseline-agent", skill_version="v1",
        status="FAILED", observed=False, error="same failure", retry_count=1,
    ))
    record = retrieve_agent_competence(
        domain="system-learning", task_class="artifact-integrity", capability_id="learning.baseline"
    )[0]
    assert record["tested_cases"] == 2
    assert record["success_rate"] == 0.5
    assert record["human_correction_rate"] == 0.5
    assert record["retry_rate"] == 1.0
    assert "same failure" in record["known_failure_modes"]


def test_failure_memory_retrieval_is_filtered():
    persist_episode(_episode(episode_id="failure-source", execution_id="exec-failure-source"))
    memory = record_memory(
        memory_type="FAILURE",
        claim="artifact identity mismatch recurs without preflight",
        domain="system-learning",
        task_class="artifact-integrity",
        failure_pattern="identity-mismatch",
        source_episode_ids=("failure-source",),
        evidence_refs=("evidence:failure",),
        capability_id="learning.baseline",
        status="ACTIVE",
    )
    found = retrieve_known_failure_patterns(
        domain="system-learning", task_class="artifact-integrity", capability="learning.baseline"
    )
    assert found[0]["memory_id"] == memory["memory_id"]


def test_learning_candidate_creation_has_episode_evidence_and_contradiction_check():
    candidate = _candidate()
    assert candidate["status"] == "CANDIDATE"
    assert candidate["source_episode_ids"] == ["source-a"]
    assert candidate["contradiction_check"]["status"] == "NO_CONTRADICTION_FOUND"


def test_candidate_rejection_on_regression():
    candidate = _candidate()
    evaluation = evaluate_candidate(
        candidate_id=candidate["candidate_id"],
        baseline_metrics=_metrics(retry_rate=0.2, human_rate=0.1, failure_recurrence=0.1),
        candidate_metrics=_metrics(retry_rate=0.0, human_rate=0.0, failure_recurrence=0.0, quality=0.5),
        trials=2,
        regression_pass=True,
        adversarial_pass=True,
        critical_regression=False,
        evidence_refs=("eval:regression",),
    )
    assert evaluation["decision"] == "REJECT_REGRESSION"


def test_candidate_rejected_when_no_measurable_improvement():
    candidate = _candidate()
    metrics = _metrics(retry_rate=0.0, human_rate=0.0, failure_recurrence=0.0)
    evaluation = evaluate_candidate(
        candidate_id=candidate["candidate_id"],
        baseline_metrics=metrics,
        candidate_metrics=metrics,
        trials=2,
        regression_pass=True,
        adversarial_pass=True,
        critical_regression=False,
        evidence_refs=("eval:no-change",),
    )
    assert evaluation["decision"] == "REJECT_NO_MEASURABLE_IMPROVEMENT"


def test_skill_and_policy_versions_are_append_only():
    skill_id = "test.learning.append-only"
    policy_id = "test.harness-routing-policy.append-only"
    skill = register_skill_version(
        skill_id=skill_id, version="v1", content_ref="skill:v1",
        checksum="a" * 64, status="ACTIVE", evidence_refs=("evidence:v1",),
    )
    policy = register_policy_version(
        policy_id=policy_id, version="v1", content_ref="policy:v1",
        checksum="b" * 64, status="ACTIVE", evidence_refs=("evidence:p1",),
    )
    assert skill["version"] == "v1"
    assert policy["version"] == "v1"
    with pytest.raises(Exception):
        register_skill_version(
            skill_id=skill_id, version="v1", content_ref="overwrite",
            checksum="c" * 64, status="ACTIVE", evidence_refs=("evidence:overwrite",),
        )

def test_promotion_requires_harness_authorization_and_creates_active_procedural_memory():
    candidate = _candidate()
    register_skill_version(
        skill_id="learning.artifact-integrity", version="v2", parent_version="v1",
        content_ref="skill:v2", checksum="d" * 64, status="CANDIDATE",
        evidence_refs=("eval:skill-v2",),
    )
    evaluation = evaluate_candidate(
        candidate_id=candidate["candidate_id"],
        baseline_metrics=_metrics(retry_rate=1.0, human_rate=0.5, failure_recurrence=0.5, latency=2.0),
        candidate_metrics=_metrics(retry_rate=0.0, human_rate=0.0, failure_recurrence=0.0, latency=1.0),
        trials=3,
        regression_pass=True,
        adversarial_pass=True,
        critical_regression=False,
        evidence_refs=("eval:promote",),
    )
    wrong = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:other",
        harness_decision_id="decision-wrong",
        execution_id="exec-wrong",
    )
    with pytest.raises(PermissionError):
        promote_candidate(
            candidate_id=candidate["candidate_id"], evaluation=evaluation, authorization=wrong,
            memory_claim="validated procedure", memory_type="PROCEDURAL",
        )
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"learning:candidate:{candidate['candidate_id']}",
        harness_decision_id="decision-promote",
        execution_id="exec-promote",
    )
    promoted = promote_candidate(
        candidate_id=candidate["candidate_id"], evaluation=evaluation, authorization=auth,
        memory_claim="preflight validation removes retry without reducing observed quality",
        memory_type="PROCEDURAL", source_versions={"skill": "v2"},
    )
    assert promoted["status"] == "PROMOTED"
    assert promoted["authority"] == "deepseek_harness"
    assert promoted["memory"]["status"] == "ACTIVE"


def test_routing_uses_active_competence_and_insufficient_evidence_does_not_override():
    registry = _registry()
    request = HarnessRoutingRequest(
        intent="artifact integrity learning",
        authorized_action="EXECUTION",
        domain="system-learning",
        task_class="artifact-integrity",
        required_policy_tags=("learning", "artifact", "integrity"),
    )
    baseline_decision = route_harness_request(request, registry=registry)
    assert baseline_decision.selected_capability_id == "learning.baseline"

    persist_episode(_episode(
        episode_id="route-base-1", execution_id="exec-route-base-1",
        capability_id="learning.baseline", agent_id="baseline-agent", skill_version="v1",
        retry_count=1, human_intervention=True,
    ))
    persist_episode(_episode(
        episode_id="route-base-2", execution_id="exec-route-base-2",
        capability_id="learning.baseline", agent_id="baseline-agent", skill_version="v1",
        retry_count=1,
    ))
    persist_episode(_episode(
        episode_id="route-candidate-1", execution_id="exec-route-candidate-1",
        capability_id="learning.candidate", agent_id="candidate-agent", skill_version="v2",
    ))
    one_case_decision, one_case_proof = route_harness_request_with_learning(
        request, goal="goal-learning", registry=registry
    )
    assert one_case_decision.selected_capability_id == "learning.baseline"
    assert len([x for x in one_case_proof["competence_records_considered"] if x["capability_id"] == "learning.candidate"]) == 0

    persist_episode(_episode(
        episode_id="route-candidate-2", execution_id="exec-route-candidate-2",
        capability_id="learning.candidate", agent_id="candidate-agent", skill_version="v2",
    ))
    learned_decision, proof = route_harness_request_with_learning(request, goal="goal-learning", registry=registry)
    assert learned_decision.selected_capability_id == "learning.candidate"
    assert proof["learning_participated"] is True
    assert learned_decision.policy_metadata["competence_evidence_used"]


def test_next_run_retrieval_uses_validated_learning():
    persist_episode(_episode(episode_id="next-run-source", execution_id="exec-next-run-source"))
    memory = record_memory(
        memory_type="PROCEDURAL",
        claim="run preflight before artifact execution",
        domain="system-learning",
        task_class="artifact-integrity",
        source_episode_ids=("next-run-source",),
        evidence_refs=("evidence:next-run",),
        status="ACTIVE",
    )
    found = retrieve_relevant_memory(
        goal="next-goal", domain="system-learning", task_class="artifact-integrity"
    )
    assert memory["memory_id"] in {item["memory_id"] for item in found}


def test_system_improvement_mission_is_harness_authorized():
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="learning:improvement",
        harness_decision_id="decision-improvement",
        execution_id="exec-improvement",
    )
    mission = create_improvement_mission(
        trigger_type="REPEATED_FAILURE",
        trigger_refs=("episode:a", "episode:b"),
        diagnosis="same integrity failure repeated",
        hypothesis="preflight should remove recurrence",
        authorization=auth,
    )
    assert mission["status"] == "AUTHORIZED"
    assert mission["harness_decision_id"] == "decision-improvement"


def test_knowledge_brain_boundary_and_publication_authority_remain_separate():
    connection = get_connection()
    try:
        before = connection.execute("SELECT COUNT(*) AS n FROM gta6_knowledge").fetchone()["n"]
    finally:
        connection.close()
    persist_episode(_episode(episode_id="boundary", execution_id="exec-boundary"))
    connection = get_connection()
    try:
        after = connection.execute("SELECT COUNT(*) AS n FROM gta6_knowledge").fetchone()["n"]
        learning_tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'harness_%'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert before == after
    assert "harness_episodes" in learning_tables
    assert "youtube_publications" not in learning_tables


def test_existing_routing_without_learning_context_remains_compatible():
    registry = _registry()
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="artifact integrity learning",
            authorized_action="EXECUTION",
            domain="system-learning",
            required_policy_tags=("learning",),
        ),
        registry=registry,
    )
    assert decision.selected_capability_id in {"learning.baseline", "learning.candidate"}
    assert decision.policy_metadata["competence_evidence_used"] == []
