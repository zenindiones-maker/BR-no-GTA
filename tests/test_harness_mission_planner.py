from app.services.harness_collaboration_service import (
    build_goal_envelope,
    plan_mission_from_human_goal,
)
from app.services.harness_learning_service import HarnessEpisode, persist_episode
from app.services.memory_plane_service import evaluate_memory_candidate
from app.services.harness_authorization_service import issue_harness_authorization
from app.database import harness_learning_repository as repository
from datetime import datetime, timezone


def _active_opencode_failure():
    now = datetime.now(timezone.utc).isoformat()
    episode = HarnessEpisode(
        episode_id="episode-planner-opencode-403",
        goal_id="goal-system-health",
        decision_id="decision-planner-opencode-403",
        execution_id="execution-planner-opencode-403",
        task_id="semantic-reasoning",
        agent_id="provider:opencode",
        capability_id="ai.reasoning.text",
        domain="ai",
        task_class="semantic-reasoning",
        started_at=now,
        finished_at=now,
        duration_seconds=0.0,
        status="BLOCKED",
        actual_outcome={"observed": True, "provider_error": "OpenCode free tier HTTP 403"},
        outcome_evidence=("evidence:opencode-403",),
        evidence_refs=("evidence:opencode-403",),
        error="OpenCode free tier HTTP 403 before inference",
    )
    persist_episode(episode)
    candidate = next(
        item for item in repository.list_memories(status="CANDIDATE", limit=50)
        if episode.episode_id in (item.get("source_episode_ids") or ())
    )
    auth = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"learning:memory:{candidate['memory_id']}",
        harness_decision_id="decision-promote-opencode-failure",
        execution_id="execution-promote-opencode-failure",
    )
    evaluate_memory_candidate(
        memory_id=candidate["memory_id"],
        decision="PROMOTE",
        reason="observed upstream admission denial",
        evidence_refs=("evidence:opencode-403",),
        authorization=auth,
    )


def test_natural_performance_goal_builds_dynamic_harness_plan_without_team_keyword():
    _active_opencode_failure()
    human_goal = (
        "Analisa onde estamos perdendo desempenho no sistema e usa a equipe necessária "
        "para melhorar o que for comprovadamente inútil, sem reduzir qualidade."
    )
    goal = build_goal_envelope(
        human_goal=human_goal,
        project="BR-no-GTA",
        goal_id="goal-system-health",
        subject="performance do sistema",
    )
    plan = plan_mission_from_human_goal(goal)

    tasks = plan.collaboration_plan.tasks
    assert goal.mission_class == "SYSTEM_IMPROVEMENT"
    assert 2 <= len(tasks) <= plan.resource_bounds["max_tasks_per_mission"]
    assert plan.collaboration_plan.authority == "DEEPSEEK_HARNESS"
    assert plan.bounded_memory_context["authority"] == "DEEPSEEK_HARNESS"
    assert plan.provider_health["opencode"]["state"] == "UPSTREAM_DENIED"
    assert "opencode_free_tier_403" in plan.known_bad_paths_avoided
    assert all(task.capability_id != "ai.provider.opencode-free" for task in tasks)
    assert any(task.task_id == "candidate" for task in tasks)
    assert any(task.task_id == "validate" for task in tasks)
    builder = next(task for task in tasks if task.task_id == "candidate")
    reviewer = next(task for task in tasks if task.task_id == "validate")
    assert builder.capability_id == "agent-office.codex.bounded-development"
    assert reviewer.capability_id != builder.capability_id
    assert "Hermes" not in human_goal
    assert "Agent Office" not in human_goal
    assert "Codex" not in human_goal


def test_open_semantic_goal_fails_explicitly_when_no_zero_cost_provider_is_healthy():
    _active_opencode_failure()
    goal = build_goal_envelope(
        human_goal="Pensa em algo totalmente novo e surpreendente para mim.",
        project="BR-no-GTA",
        goal_id="goal-open-semantic",
    )
    try:
        plan_mission_from_human_goal(goal)
    except RuntimeError as exc:
        assert str(exc) == "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE"
    else:
        raise AssertionError("open semantic goal must not silently bypass provider health")
