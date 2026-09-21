from app.services.harness_adaptive_planning_service import (
    propose_validated_semantic_plan,
    select_capability_for_requirement,
)
from app.services.harness_collaboration_service import (
    build_goal_envelope,
    plan_mission_from_human_goal,
)


def _proposal(*, candidate_id: str):
    return {
        "interpreted_goal": "Investigar o problema antes de alterar o sistema.",
        "assumptions": ["mudanças precisam de evidência"],
        "required_outcomes": ["causa comprovada"],
        "tasks": [
            {
                "task_id": "inspect",
                "objective": "inspecionar evidência existente sem modificar o sistema",
                "task_class": "system-root-cause-analysis",
                "required_capability_description": "análise de sistema read-only com evidência",
                "candidate_capability_ids": [candidate_id],
                "dependencies": [],
                "expected_output": "RootCauseEvidence",
                "acceptance_criteria": ["causa apoiada por evidência"],
                "risk_side_effect_class": "READ_ONLY",
                "action": "DEVELOPMENT",
            }
        ],
        "rationale": "observar antes de intervir",
        "uncertainty": 0.25,
        "needs_human_clarification": False,
        "clarification_question": None,
        "memory_strategy_notes": [],
        "reused_artifact_refs": [],
        "avoided_bad_paths": [],
    }


def test_semantic_proposal_with_invented_capability_is_rejected_then_replanned_once():
    context = {
        "human_goal": "Descobre sozinho por que isso está estranho.",
        "project": "BR-no-GTA",
        "goal_id": "goal-replan",
        "subject": "system",
        "conversation_state": {},
        "bounded_memory_context": {},
        "relevant_failure_memories": [],
        "human_feedback_decisions": [],
        "provider_health": {},
        "registry_summary": [],
        "competence_evidence": [],
        "resource_bounds": {"max_tasks_per_mission": 8},
        "known_bad_paths": [],
    }
    calls = []

    def inference(prompt, _context):
        calls.append(prompt)
        if len(calls) == 1:
            return _proposal(candidate_id="capability.that.does.not.exist")
        return _proposal(candidate_id="agent-office.codex.readonly-analysis")

    result, evidence = propose_validated_semantic_plan(
        context,
        inference=inference,
        max_replans=1,
    )

    assert result.proposal.tasks[0].candidate_capability_ids == (
        "agent-office.codex.readonly-analysis",
    )
    assert len(calls) == 2
    assert evidence["replan_count"] == 1
    assert evidence["proposal_attempts"] == 2
    assert any(
        "does not exist in Registry" in reason
        for batch in evidence["rejection_reasons"]
        for reason in batch
    )
    assert evidence["planner_authority"] == "NONE"
    assert evidence["validated_by"] == "DEEPSEEK_HARNESS"


def test_competence_can_override_semantic_candidate_hint():
    requirement = {
        "task_id": "inspect",
        "task_class": "system-root-cause-analysis",
        "action": "DEVELOPMENT",
        "query": "system improvement evidence proposal analysis",
        "objective": "analisar o sistema com evidência",
        "candidate_capability_ids": [
            "agent-office.codex.readonly-analysis",
            "system.improvement.propose",
        ],
        "dependencies": [],
        "expected_output": "Evidence",
        "acceptance_criteria": ["evidence"],
        "risk_side_effect_class": "READ_ONLY",
    }
    context = {
        "relevant_failure_memories": [],
        "competence_evidence": [
            {
                "capability_id": "agent-office.codex.readonly-analysis",
                "task_class": "system-root-cause-analysis",
                "version": "1",
                "tested_cases": 20,
                "success_rate": 0.40,
                "failure_rate": 0.35,
                "human_correction_rate": 0.20,
                "retry_rate": 0.30,
                "mean_latency_seconds": 180.0,
                "mean_cost": 0.0,
                "freshness_score": 1.0,
                "confidence": 0.8,
            },
            {
                "capability_id": "system.improvement.propose",
                "task_class": "system-root-cause-analysis",
                "version": "1",
                "tested_cases": 40,
                "success_rate": 0.95,
                "failure_rate": 0.025,
                "human_correction_rate": 0.025,
                "retry_rate": 0.025,
                "mean_latency_seconds": 2.0,
                "mean_cost": 0.0,
                "freshness_score": 1.0,
                "confidence": 0.95,
            },
        ],
    }

    selected, competence_used, _avoided, evidence = select_capability_for_requirement(
        requirement,
        context=context,
        used=set(),
    )

    assert selected == "system.improvement.propose"
    assert competence_used is True
    assert evidence["competence_used"] is True
    assert evidence["competence_evidence"]["tested_cases"] == 40


def test_known_failure_memory_removes_bad_capability_before_selection():
    requirement = {
        "task_id": "inspect",
        "task_class": "system-root-cause-analysis",
        "action": "DEVELOPMENT",
        "query": "system improvement proposal evidence analysis",
        "objective": "analisar causa",
        "candidate_capability_ids": [
            "system.improvement.propose",
            "agent-office.codex.readonly-analysis",
        ],
        "dependencies": [],
        "expected_output": "Evidence",
        "acceptance_criteria": ["evidence"],
        "risk_side_effect_class": "READ_ONLY",
    }
    context = {
        "relevant_failure_memories": [
            {
                "memory_id": "memory-bad-system-proposal",
                "capability_id": "system.improvement.propose",
                "failure_pattern": "repeated_unhelpful_plan",
                "confidence": 0.9,
            }
        ],
        "competence_evidence": [],
    }

    selected, _competence_used, avoided, _evidence = select_capability_for_requirement(
        requirement,
        context=context,
        used=set(),
    )

    assert selected != "system.improvement.propose"
    assert "repeated_unhelpful_plan" in avoided


def test_ambiguous_natural_goal_uses_dynamic_semantic_dag_without_agent_names():
    human_goal = "O áudio melhorou mas alguma coisa ainda está estranha. Descobre o que é antes de mexer."
    goal = build_goal_envelope(
        human_goal=human_goal,
        project="BR-no-GTA",
        goal_id="goal-audio-strange",
        subject="qualidade audiovisual",
        conversation_state={"previous_result": "audio improved"},
    )

    def inference(_prompt, context):
        assert context["conversation_state"]["previous_result"] == "audio improved"
        return {
            "interpreted_goal": "diagnosticar a regressão residual antes de qualquer mutação",
            "assumptions": ["o áudio já melhorou em relação ao baseline anterior"],
            "required_outcomes": [
                "localizar o componente responsável",
                "separar diagnóstico de mudança",
                "validar qualquer correção contra o baseline",
            ],
            "tasks": [
                {
                    "task_id": "inspect-output",
                    "objective": "inspecionar tecnicamente o resultado atual e localizar sinais anormais",
                    "task_class": "media-anomaly-analysis",
                    "required_capability_description": "análise técnica de mídia existente",
                    "candidate_capability_ids": ["agent-office.codex.readonly-analysis"],
                    "dependencies": [],
                    "expected_output": "MediaAnomalyEvidence",
                    "acceptance_criteria": ["anomalia localizada ou hipótese explicitamente refutada"],
                    "risk_side_effect_class": "READ_ONLY",
                    "action": "EXECUTION",
                },
                {
                    "task_id": "trace-cause",
                    "objective": "rastrear a anomalia observada até a etapa de pipeline responsável",
                    "task_class": "system-root-cause-analysis",
                    "required_capability_description": "análise read-only de pipeline e configuração",
                    "candidate_capability_ids": ["agent-office.codex.readonly-analysis"],
                    "dependencies": ["inspect-output"],
                    "expected_output": "RootCauseEvidence",
                    "acceptance_criteria": ["causa ligada à evidência de mídia"],
                    "risk_side_effect_class": "READ_ONLY",
                    "action": "DEVELOPMENT",
                },
                {
                    "task_id": "decide-next",
                    "objective": "propor a menor intervenção somente se a causa estiver comprovada",
                    "task_class": "system-improvement-decision",
                    "required_capability_description": "proposta de melhoria limitada por evidência",
                    "candidate_capability_ids": ["system.improvement.propose"],
                    "dependencies": ["trace-cause"],
                    "expected_output": "BoundedImprovementProposal",
                    "acceptance_criteria": ["nenhuma mutação sem causa comprovada"],
                    "risk_side_effect_class": "READ_ONLY",
                    "action": "DEVELOPMENT",
                },
            ],
            "rationale": "o pedido pede diagnóstico antes de mexer, então não há candidate patch antecipado",
            "uncertainty": 0.35,
            "needs_human_clarification": False,
            "clarification_question": None,
            "memory_strategy_notes": ["usar o resultado anterior como baseline contextual"],
            "reused_artifact_refs": [],
            "avoided_bad_paths": [],
        }

    plan = plan_mission_from_human_goal(
        goal,
        semantic_inference=inference,
    )
    task_ids = [task.task_id for task in plan.collaboration_plan.tasks]

    assert plan.planning_mode == "SEMANTIC_ADAPTIVE"
    assert task_ids == ["inspect-output", "trace-cause", "decide-next"]
    assert task_ids != ["measure", "root-cause", "candidate", "validate"]
    assert plan.planning_evidence["semantic_provider_call_count"] == 1
    assert plan.planning_evidence["harness_validated"] is True
    assert plan.goal.conversation_state["previous_result"] == "audio improved"
    assert "Codex" not in human_goal
    assert "Agent Office" not in human_goal
    assert "Hermes" not in human_goal


def test_simple_high_confidence_system_goal_uses_zero_semantic_provider_calls():
    goal = build_goal_envelope(
        human_goal="Melhora o sistema sem reduzir qualidade.",
        project="BR-no-GTA",
        goal_id="goal-simple-fast-path",
        subject="pipeline",
    )

    plan = plan_mission_from_human_goal(goal)

    assert plan.planning_mode == "DETERMINISTIC_FAST_PATH"
    assert plan.planning_evidence["semantic_provider_call_count"] == 0
    assert plan.authority == "DEEPSEEK_HARNESS"
