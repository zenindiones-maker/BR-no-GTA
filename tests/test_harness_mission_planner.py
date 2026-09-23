from app.services.harness_mission_execution_router import select_mission_execution_route
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

    def semantic_inference(_prompt, _context):
        return {
            "interpreted_goal": "Encontrar desperdício comprovável e só então propor mudança segura.",
            "assumptions": ["qualidade e autoridade não podem regredir"],
            "required_outcomes": [
                "evidência do desperdício",
                "causa explicada",
                "mudança candidata isolada",
                "comparação independente",
            ],
            "tasks": [
                {
                    "task_id": "profile-waste",
                    "objective": "medir chamadas e trabalho evitável antes de mudar o sistema",
                    "task_class": "system-performance-measure",
                    "required_capability_description": "observabilidade e análise de desempenho do sistema",
                    "candidate_capability_ids": ["system.improvement.propose"],
                    "dependencies": [],
                    "expected_output": "MeasuredWasteEvidence",
                    "acceptance_criteria": ["desperdício sustentado por evidência"],
                    "risk_side_effect_class": "READ_ONLY",
                    "action": "DEVELOPMENT",
                },
                {
                    "task_id": "isolate-cause",
                    "objective": "explicar a causa mínima do trabalho evitável observado",
                    "task_class": "system-root-cause-analysis",
                    "required_capability_description": "análise de código read-only com evidência",
                    "candidate_capability_ids": ["agent-office.codex.readonly-analysis"],
                    "dependencies": ["profile-waste"],
                    "expected_output": "RootCauseEvidence",
                    "acceptance_criteria": ["causa ligada à medição anterior"],
                    "risk_side_effect_class": "READ_ONLY",
                    "action": "DEVELOPMENT",
                },
                {
                    "task_id": "bounded-fix",
                    "objective": "criar candidato mínimo apenas para a causa comprovada",
                    "task_class": "bounded-development",
                    "required_capability_description": "desenvolvimento isolado em worktree com testes",
                    "candidate_capability_ids": ["agent-office.codex.bounded-development"],
                    "dependencies": ["isolate-cause"],
                    "expected_output": "BoundedCandidatePatch",
                    "acceptance_criteria": ["candidate isolado", "testes focados passam"],
                    "risk_side_effect_class": "MEDIUM",
                    "action": "DEVELOPMENT",
                },
                {
                    "task_id": "independent-compare",
                    "objective": "comparar baseline e candidato sem autoaprovação",
                    "task_class": "candidate-validation",
                    "required_capability_description": "review read-only independente com benchmark",
                    "candidate_capability_ids": ["agent-office.codex.readonly-analysis"],
                    "dependencies": ["bounded-fix"],
                    "expected_output": "BaselineCandidateComparison",
                    "acceptance_criteria": ["sem regressão de qualidade", "ganho mensurável"],
                    "risk_side_effect_class": "READ_ONLY",
                    "action": "DEVELOPMENT",
                },
            ],
            "rationale": "medir antes de mudar e validar separadamente",
            "uncertainty": 0.2,
            "needs_human_clarification": False,
            "clarification_question": None,
            "memory_strategy_notes": ["evitar provider previamente bloqueado"],
            "reused_artifact_refs": [],
            "avoided_bad_paths": ["opencode_free_tier_403"],
        }

    plan = plan_mission_from_human_goal(
        goal,
        semantic_inference=semantic_inference,
    )

    tasks = plan.collaboration_plan.tasks
    assert goal.mission_class == "SYSTEM_IMPROVEMENT"
    assert plan.planning_mode == "SEMANTIC_ADAPTIVE"
    assert 2 <= len(tasks) <= plan.resource_bounds["max_tasks_per_mission"]
    assert plan.collaboration_plan.authority == "DEEPSEEK_HARNESS"
    assert plan.bounded_memory_context["authority"] == "DEEPSEEK_HARNESS"
    assert plan.provider_health["opencode"]["state"] == "UPSTREAM_DENIED"
    assert any("opencode" in item for item in plan.known_bad_paths_avoided)
    assert all(task.capability_id != "ai.provider.opencode-free" for task in tasks)
    assert plan.planning_evidence["semantic_provider_call_count"] == 2
    assert plan.planning_evidence["proposal_attempts"] == 2
    assert plan.planning_evidence["replan_count"] == 1
    assert any(
        "execution-contract-insufficient" in reason
        for row in plan.planning_evidence["rejection_reasons"]
        for reason in row
    )
    assert plan.planning_evidence["harness_validated"] is True
    assert "Hermes" not in human_goal
    assert "Agent Office" not in human_goal
    assert "Codex" not in human_goal

def _authorized_private_review_goal():
    return build_goal_envelope(
        human_goal=(
            "Produza um vídeo GTA 6 real com pipeline multiagente completo e "
            "MASTER_FINAL PRIVATE para revisão HD humana. Não publique public "
            "nem unlisted."
        ),
        project="BR-no-GTA",
        goal_id="goal-explicit-private-review",
        subject="real multi-agent GTA6 audiovisual production",
        source_surface="work",
        canonical_state={
            "human_goal_execution_authorized": True,
            "youtube_private_hd_review": "ALLOWED",
            "youtube_publication_public": "FORBIDDEN",
            "youtube_publication_unlisted": "FORBIDDEN",
        },
    )


def _clarifying_research_proposal(question):
    return {
        "interpreted_goal": "Executar a produção privada explicitamente solicitada.",
        "assumptions": [],
        "required_outcomes": ["evidência atual"],
        "tasks": [{
            "task_id": "research-evidence",
            "objective": "collect fresh evidence from current GTA6 official sources",
            "task_class": "evidence-collection",
            "required_capability_description": "fresh GTA6 evidence collection",
            "candidate_capability_ids": ["gta6.research"],
            "dependencies": [],
            "expected_output": "fresh research artifact",
            "acceptance_criteria": ["fresh official evidence"],
            "risk_side_effect_class": "READ_ONLY",
            "action": "RESEARCH",
        }],
        "rationale": "Use only already-authorized private review scope.",
        "context_usage_notes": [],
        "uncertainty": 0.1,
        "needs_human_clarification": True,
        "clarification_question": question,
        "memory_strategy_notes": [],
        "reused_artifact_refs": [],
        "avoided_bad_paths": [],
    }


def test_explicit_human_goal_resolves_redundant_private_review_confirmation():
    goal = _authorized_private_review_goal()
    plan = plan_mission_from_human_goal(
        goal,
        semantic_inference=lambda _prompt, _context: _clarifying_research_proposal(
            "Confirmar execução do pipeline completo multiagente para vídeo GTA 6 "
            "real com master PRIVATE para revisão HD?"
        ),
    )
    assert (
        plan.planning_evidence["clarification_resolution"]
        == "EXPLICIT_HUMAN_GOAL_AUTHORIZATION"
    )
    assert plan.semantic_plan_proposal["needs_human_clarification"] is False
    assert plan.semantic_plan_proposal["clarification_question"] is None


def test_explicit_private_authorization_does_not_clear_forbidden_public_scope():
    goal = _authorized_private_review_goal()
    try:
        plan_mission_from_human_goal(
            goal,
            semantic_inference=lambda _prompt, _context: _clarifying_research_proposal(
                "Confirmar upload PUBLIC do vídeo GTA 6 real?"
            ),
        )
    except RuntimeError as exc:
        assert str(exc).startswith("MISSION_NEEDS_HUMAN_CLARIFICATION:")
    else:
        raise AssertionError("forbidden PUBLIC scope must keep the human gate")


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



def test_execution_router_keeps_known_missions_off_provider_fallback():
    _active_opencode_failure()

    improvement = plan_mission_from_human_goal(build_goal_envelope(
        human_goal="Melhora o sistema sem reduzir qualidade.",
        project="BR-no-GTA",
        goal_id="goal-router-system",
        subject="pipeline lento",
    ))
    improvement_route = select_mission_execution_route(improvement.to_dict())
    assert improvement_route.runtime == "HERMES_KANBAN"
    assert improvement_route.hermes_used is True
    assert improvement_route.provider_required is False
    assert "SYSTEM_IMPROVEMENT" not in improvement_route.runtime

    gta6 = plan_mission_from_human_goal(build_goal_envelope(
        human_goal="O que sabemos sobre Jason no GTA 6?",
        project="BR-no-GTA",
        goal_id="goal-router-gta6",
        subject="Jason Duval",
    ))
    gta6_route = select_mission_execution_route(gta6.to_dict())
    assert gta6_route.runtime == "HERMES_KANBAN"
    assert gta6_route.hermes_used is True
    assert gta6_route.provider_required is False
    assert "GTA6" not in gta6_route.runtime

    editorial = plan_mission_from_human_goal(build_goal_envelope(
        human_goal="Revisa o roteiro e melhora a estratégia editorial.",
        project="BR-no-GTA",
        goal_id="goal-router-editorial",
        subject="script:8",
    ))
    editorial_route = select_mission_execution_route(editorial.to_dict())
    assert editorial_route.runtime == "HERMES_KANBAN"
    assert editorial_route.hermes_used is True
    assert editorial_route.task_count >= 2
    assert editorial_route.provider_required is False


def test_system_improvement_rejects_research_fact_check_before_registry_execution():
    _active_opencode_failure()
    human_goal = (
        "Analise o BR-no-GTA atual e encontre sozinho uma perda mensurável de desempenho, "
        "redundância, trabalho desnecessário ou fragilidade arquitetural. Escolha a equipe "
        "mínima adequada, investigue, proponha uma melhoria segura, implemente um candidate "
        "isolado se for necessário, revise independentemente e compare antes/depois."
    )
    goal = build_goal_envelope(
        human_goal=human_goal,
        project="BR-no-GTA",
        goal_id="goal-system-action-policy",
        subject="melhoria arquitetural mensurável",
    )
    attempts = []

    invalid = {
        "interpreted_goal": "Verificar melhoria arquitetural mensurável com evidência.",
        "assumptions": [],
        "required_outcomes": ["verificação independente"],
        "tasks": [
            {
                "task_id": "verify-improvement",
                "objective": "Verificar a melhoria e ausência de regressão.",
                "task_class": "candidate-validation",
                "required_capability_description": "",
                "candidate_capability_ids": ["gta6.fact-check"],
                "dependencies": [],
                "expected_output": "IndependentVerification",
                "acceptance_criteria": ["evidência verificável sem regressão"],
                "risk_side_effect_class": "READ_ONLY",
                "action": "RESEARCH",
            }
        ],
        "rationale": "verificar antes de qualquer promoção",
        "context_usage_notes": [],
        "uncertainty": 0.2,
        "needs_human_clarification": False,
        "clarification_question": None,
        "memory_strategy_notes": [],
        "reused_artifact_refs": [],
        "avoided_bad_paths": [],
    }
    valid = {
        **invalid,
        "tasks": [
            {
                **invalid["tasks"][0],
                "required_capability_description": (
                    "independent read-only engineering verification with regression evidence"
                ),
                "candidate_capability_ids": [],
                "action": "DEVELOPMENT",
            }
        ],
    }

    def semantic_inference(prompt, _context):
        attempts.append(prompt)
        return invalid if len(attempts) == 1 else valid

    plan = plan_mission_from_human_goal(
        goal,
        semantic_inference=semantic_inference,
    )

    assert goal.mission_class == "SYSTEM_IMPROVEMENT"
    assert len(attempts) == 2
    assert len(plan.collaboration_plan.tasks) == 1
    task = plan.collaboration_plan.tasks[0]
    assert task.action == "DEVELOPMENT"
    assert task.capability_id != "gta6.fact-check"
    rejection_rows = plan.planning_evidence["rejection_reasons"]
    assert any(
        "mission_class=SYSTEM_IMPROVEMENT" in reason
        for row in rejection_rows
        for reason in row
    )
    assert "SYSTEM_IMPROVEMENT tasks must use DEVELOPMENT" in attempts[1]
