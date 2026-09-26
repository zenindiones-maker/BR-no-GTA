import app.services.harness_adaptive_planning_service as adaptive_service
from app.services.harness_adaptive_planning_service import (
    _relevant_registry_summary,
    propose_validated_semantic_plan,
    select_capability_for_requirement,
)
from app.services.provider_health_service import provider_health
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    expand_compact_mission_plan_mapping,
    mission_plan_json_schema,
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




def test_provider_health_does_not_confuse_harness_authorization_with_external_auth():
    opencode = provider_health("opencode")
    nvidia = provider_health("nvidia_nim")

    assert opencode.state == "UPSTREAM_DENIED"
    assert opencode.zero_cost_eligible is True
    assert opencode.retry_allowed is False
    assert opencode.reason == "opencode_console_free_tier_403_before_inference"
    assert "github:run:35546356452:opencode-semantic-v3-upstream-403" in opencode.evidence_refs
    assert nvidia.state == "AUTH_REQUIRED"
    assert nvidia.zero_cost_eligible is True
    assert nvidia.reason == "Provider requires runtime authentication evidence."



def test_semantic_context_retrieval_is_bounded_and_keeps_relevant_system_capabilities():
    rows = _relevant_registry_summary(
        {
            "human_goal": "Isso está uma carroça, descobre sozinho o que está acontecendo.",
            "subject": "desempenho geral do sistema",
            "mission_class": "SYSTEM_IMPROVEMENT",
        }
    )
    ids = [str(item["capability_id"]) for item in rows]

    assert 6 <= len(rows) <= 8
    assert len(ids) == len(set(ids))
    assert "system.improvement.propose" in ids
    assert all(item["type"] != "PROVIDER" for item in rows)
    assert all("actions" in item for item in rows)

def test_compact_wire_expands_to_canonical_mission_plan():
    wire = {
        "g": "Diagnosticar lentidão antes de alterar.",
        "a": ["causa ainda não comprovada"],
        "o": ["causa comprovada"],
        "t": [
            {
                "id": "inspect",
                "obj": "medir gargalo observado",
                "cls": "system-root-cause-analysis",
                "need": "",
                "caps": ["agent-office.codex.readonly-analysis"],
                "dep": [],
                "out": "RootCauseEvidence",
                "ok": ["causa ligada a evidência"],
                "risk": "RO",
                "act": "D",
            }
        ],
        "why": "Observar antes de mutar.",
        "ctx": ["latência aumentou"],
        "u": 0.25,
        "ask": False,
        "q": None,
        "mem": [],
        "reuse": [],
        "avoid": [],
    }
    canonical = expand_compact_mission_plan_mapping(wire)
    proposal = MissionPlanProposal.from_mapping(canonical, max_tasks=8)

    assert proposal.tasks[0].action == "DEVELOPMENT"
    assert proposal.tasks[0].risk_side_effect_class == "READ_ONLY"
    assert proposal.tasks[0].required_capability_description == ""
    assert proposal.tasks[0].candidate_capability_ids == (
        "agent-office.codex.readonly-analysis",
    )


def test_compact_native_schema_uses_short_wire_keys():
    schema = mission_plan_json_schema(max_tasks=8)

    assert "g" in schema["properties"]
    assert "t" in schema["properties"]
    assert "interpreted_goal" not in schema["properties"]
    task = schema["properties"]["t"]["items"]
    assert "obj" in task["properties"]
    assert "caps" in task["properties"]
    assert task["properties"]["act"]["enum"] == ["C", "D", "E", "R", "X"]
    assert task["properties"]["risk"]["enum"] == ["EXT", "H", "L", "M", "RO"]


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
            assert "CONTEXT=" in prompt
            return _proposal(candidate_id="capability.that.does.not.exist")
        assert "The previous proposal was rejected by DeepSeek Harness validation." in prompt
        assert "capability.that.does.not.exist" in prompt
        assert "does not exist in Registry" in prompt
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


def test_semantic_schema_rejection_replans_once_with_exact_enum_feedback():
    context = {
        "human_goal": "Descobre sozinho uma melhoria mensurável e segura.",
        "project": "BR-no-GTA",
        "goal_id": "goal-schema-replan",
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
        proposal = _proposal(
            candidate_id="agent-office.codex.readonly-analysis"
        )
        if len(calls) == 1:
            proposal["tasks"][0]["risk_side_effect_class"] = (
                "LOW RISK; STRICTLY READ-ONLY EXECUTION."
            )
            return proposal
        assert (
            "The previous proposal failed DeepSeek Harness schema validation."
            in prompt
        )
        assert "unsupported risk_side_effect_class" in prompt
        assert "RO|L|M|H|EXT" in prompt
        return proposal

    result, evidence = propose_validated_semantic_plan(
        context,
        inference=inference,
        max_replans=1,
    )

    assert result.proposal.tasks[0].risk_side_effect_class == "READ_ONLY"
    assert len(calls) == 2
    assert evidence["proposal_attempts"] == 2
    assert evidence["replan_count"] == 1
    assert any(
        "schema_validation:ValueError:unsupported risk_side_effect_class"
        in reason
        for batch in evidence["rejection_reasons"]
        for reason in batch
    )
    assert evidence["planner_authority"] == "NONE"
    assert evidence["validated_by"] == "DEEPSEEK_HARNESS"


def test_semantic_overlong_goal_replans_with_explicit_wire_bounds():
    context = {
        "human_goal": "Analise o sistema e encontre uma melhoria mensurável segura.",
        "project": "BR-no-GTA",
        "goal_id": "goal-bounded-string-replan",
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
        proposal = _proposal(
            candidate_id="agent-office.codex.readonly-analysis"
        )
        if len(calls) == 1:
            proposal["interpreted_goal"] = "x" * 161
            return proposal
        assert (
            "The previous proposal failed DeepSeek Harness schema validation."
            in prompt
        )
        assert "interpreted_goal exceeds bounded length" in prompt
        assert "g<=160" in prompt
        assert "obj<=140" in prompt
        assert "out<=96" in prompt
        return proposal

    result, evidence = propose_validated_semantic_plan(
        context,
        inference=inference,
        max_replans=1,
    )

    assert len(result.proposal.interpreted_goal) <= 160
    assert len(calls) == 2
    assert evidence["proposal_attempts"] == 2
    assert evidence["replan_count"] == 1
    assert any(
        "schema_validation:ValueError:interpreted_goal exceeds bounded length"
        in reason
        for batch in evidence["rejection_reasons"]
        for reason in batch
    )


def test_semantic_assumption_overflow_replans_with_explicit_collection_bounds():
    context = {
        "human_goal": "Analise o sistema e encontre uma melhoria mensurável segura.",
        "project": "BR-no-GTA",
        "goal_id": "goal-collection-bound-replan",
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
        proposal = _proposal(
            candidate_id="agent-office.codex.readonly-analysis"
        )
        if len(calls) == 1:
            proposal["assumptions"] = ["a", "b", "c"]
            return proposal
        assert "assumptions exceeds bounded item count" in prompt
        assert "a<=2 items" in prompt
        assert "o<=4" in prompt
        assert "task caps<=3" in prompt
        assert "task ok<=2" in prompt
        return proposal

    result, evidence = propose_validated_semantic_plan(
        context,
        inference=inference,
        max_replans=1,
    )

    assert len(result.proposal.assumptions) <= 2
    assert len(calls) == 2
    assert evidence["proposal_attempts"] == 2
    assert evidence["replan_count"] == 1
    assert any(
        "schema_validation:ValueError:assumptions exceeds bounded item count"
        in reason
        for batch in evidence["rejection_reasons"]
        for reason in batch
    )


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
                    "objective": "inspecionar evidência técnica já produzida do resultado atual e localizar sinais anormais",
                    "task_class": "media-anomaly-analysis",
                    "required_capability_description": "análise read-only de artifacts e evidência técnica de mídia",
                    "candidate_capability_ids": ["agent-office.codex.readonly-analysis"],
                    "dependencies": [],
                    "expected_output": "MediaAnomalyEvidence",
                    "acceptance_criteria": ["anomalia localizada ou hipótese explicitamente refutada"],
                    "risk_side_effect_class": "READ_ONLY",
                    "action": "DEVELOPMENT",
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


def test_mission_plan_normalizes_mutating_candidate_without_semantic_replan(
    monkeypatch,
):
    class _HealthyCandidate:
        state = "AVAILABLE"
        reason = "unit normalization fixture"
        confidence = 1.0
        sample_size = 1
        evidence_refs = ("test:healthy-candidate",)

        def to_dict(self):
            return {
                "state": self.state,
                "reason": self.reason,
                "confidence": self.confidence,
                "sample_size": self.sample_size,
                "evidence_refs": list(self.evidence_refs),
            }

    # Isolate TaskEnvelope normalization from live Codex auth/failure memory.
    # Runtime external-auth fail-closed behavior remains covered elsewhere.
    monkeypatch.setattr(
        adaptive_service,
        "_profiled_capability_health",
        lambda capability_id: _HealthyCandidate(),
    )
    monkeypatch.setattr(
        adaptive_service,
        "_capability_failure_memory",
        lambda capability_id, *, context: None,
    )

    goal = build_goal_envelope(
        human_goal=(
            "Descobre a causa do gargalo e, somente se houver evidência, "
            "implemente uma correção limitada."
        ),
        project="BR-no-GTA",
        goal_id="goal-task-envelope-candidate-normalization",
        subject="system performance",
    )
    calls = []

    def inference(prompt, _context):
        calls.append(prompt)
        candidate_risk = "LOW"
        return {
            "interpreted_goal": (
                "Diagnosticar o gargalo e implementar somente uma correção "
                "bounded quando a evidência justificar."
            ),
            "assumptions": ["mutação depende de diagnóstico"],
            "required_outcomes": ["causa comprovada", "candidate bounded se necessário"],
            "tasks": [
                {
                    "task_id": "diagnose-system",
                    "objective": "medir e localizar o gargalo sem modificar arquivos",
                    "task_class": "system-root-cause-analysis",
                    "required_capability_description": "",
                    "candidate_capability_ids": [
                        "agent-office.codex.readonly-analysis"
                    ],
                    "dependencies": [],
                    "expected_output": "RootCauseEvidence",
                    "acceptance_criteria": ["causa ligada a evidência"],
                    "risk_side_effect_class": "READ_ONLY",
                    "action": "DEVELOPMENT",
                },
                {
                    "task_id": "apply-bounded-change",
                    "objective": "produzir candidate local somente se a causa justificar",
                    "task_class": "adaptive-code-change",
                    "required_capability_description": "",
                    "candidate_capability_ids": [
                        "agent-office.codex.bounded-development"
                    ],
                    "dependencies": ["diagnose-system"],
                    "expected_output": "BoundedCandidatePatch",
                    "acceptance_criteria": [
                        "mudança fica no escopo autorizado",
                        "candidate depende da evidência do diagnóstico",
                    ],
                    "risk_side_effect_class": candidate_risk,
                    "action": "DEVELOPMENT",
                },
            ],
            "rationale": "observação precede qualquer mutação",
            "uncertainty": 0.2,
            "needs_human_clarification": False,
            "clarification_question": None,
            "memory_strategy_notes": [],
            "reused_artifact_refs": [],
            "avoided_bad_paths": [],
        }

    plan = plan_mission_from_human_goal(goal, semantic_inference=inference)
    tasks = {task.task_id: task for task in plan.collaboration_plan.tasks}
    candidate = tasks["apply-bounded-change"]

    assert len(calls) == 1
    assert candidate.capability_id == "agent-office.codex.bounded-development"
    assert candidate.write_scope
    assert candidate.risk_side_effect_class == "BOUNDED_MUTATION"
    assert candidate.candidate_requirement == "CONDITIONAL"
    assert "CAN_MUTATE_CANDIDATE" in candidate.required_operations
    assert "CAN_WRITE_REPOSITORY" in candidate.required_operations
    assert "CAN_RUN_TESTS" in candidate.required_operations
    assert plan.planning_evidence["semantic_provider_call_count"] == 1
    assert int(plan.planning_evidence.get("replan_count") or 0) == 0
    assert plan.authority == "DEEPSEEK_HARNESS"

def test_presentation_task_that_outputs_production_plan_is_normalized_before_selection():
    canonical = _proposal(candidate_id="")
    canonical["tasks"][0].update({
        "task_id": "production-plan",
        "objective": "prepare the audiovisual production plan",
        "task_class": "presentation",
        "required_capability_description": "prepare a production plan",
        "candidate_capability_ids": [],
        "expected_output": "ProductionPlan",
        "acceptance_criteria": ["typed production plan"],
        "action": "EXECUTION",
    })
    proposal = MissionPlanProposal.from_mapping(canonical, max_tasks=8)

    normalized, task_ids = adaptive_service._normalize_production_plan_output_contract(
        proposal
    )

    assert task_ids == ("production-plan",)
    assert normalized.tasks[0].task_class == "production-planning"
    assert normalized.tasks[0].expected_output == "ProductionPlan"

def test_unsupported_action_fails_closed_before_normalization():
    canonical = _proposal(candidate_id="")
    canonical["tasks"][0]["action"] = "EXECUTE"
    import pytest
    with pytest.raises(ValueError):
        MissionPlanProposal.from_mapping(canonical, max_tasks=8)

