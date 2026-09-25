from types import SimpleNamespace

from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_PRODUCE_ARTIFACT_REFS,
    CAN_SEMANTIC_REASONING,
    derive_required_operations,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
import app.services.harness_adaptive_planning_service as adaptive_planning
from app.services.harness_adaptive_planning_service import (
    proposal_registry_errors,
    proposal_requirements,
    select_capability_for_requirement,
)
from app.services.native_capability_adapters import execute_production_plan_capability
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    MissionTaskProposal,
)
from app.services.task_result_envelope_service import build_task_result_envelope
from app.services.ai_provider import AIProviderError
from app.services.hermes_multiagent.capability_broker import (
    DelegatedCapabilityFailure,
)
from scripts.real_multi_agent_production import (
    MAX_LONGFORM_EVIDENCE_EXPANSIONS,
    MAX_LONGFORM_EXPANSION_FACT_CHECKS,
    MAX_LONGFORM_RECOVERY_CHILD_TASKS,
    MAX_LONGFORM_WEB_EVIDENCE_SNAPSHOTS,
    MAX_LONGFORM_WEB_SOURCE_ACQUISITIONS,
    PRE_TTS_DURATION_TOLERANCE_MINUTES,
    VOICE_B_EFFECTIVE_PLANNING_WPM,
    _bounded_youtube_semantic_context,
    _classify_web_failure,
    _fresh_research_candidates,
    _governed_web_acquisition_status,
    _is_longform_underdelivery_failure,
    _longform_expansion_terminal_error,
    _longform_fallback_source_urls,
    _longform_recovery_gate_outcome,
    _longform_retry_target_seconds,
    _novelty_gate,
    _payload_for_task,
    _partition_longform_fresh_candidates,
    _target_duration_seconds,
    _web_acquisition_slots,
    _web_source_statement,
)


def _ops(capability_id: str) -> set[str]:
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    assert record is not None
    return set(record.execution_operations)


def _task(
    task_id: str,
    objective: str,
    task_class: str,
    capability_id: str,
    *,
    action: str,
    dependencies=(),
    risk: str = "READ_ONLY",
) -> MissionTaskProposal:
    return MissionTaskProposal(
        task_id=task_id,
        objective=objective,
        task_class=task_class,
        required_capability_description="",
        candidate_capability_ids=(capability_id,),
        dependencies=tuple(dependencies),
        expected_output="persisted evidence artifact",
        acceptance_criteria=("preserve direct lineage",),
        risk_side_effect_class=risk,
        action=action,
    )


def test_truthful_research_and_production_execution_operations():
    assert _ops("gta6.research") == {CAN_PRODUCE_ARTIFACT_REFS}
    assert CAN_SEMANTIC_REASONING not in _ops("gta6.knowledge.retrieve")
    assert _ops("gta6.knowledge.retrieve") == {
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }

    # The current fact-check binding is deterministic caller-supplied evidence
    # assessment. It must not masquerade as semantic reasoning or TaskResult IO.
    assert CAN_SEMANTIC_REASONING not in _ops("gta6.fact-check")
    assert CAN_CONSUME_ARTIFACT_REFS not in _ops("gta6.fact-check")
    assert CAN_PRODUCE_ARTIFACT_REFS not in _ops("gta6.fact-check")

    assert _ops("gta6.research.fresh-cloud") == {CAN_PRODUCE_ARTIFACT_REFS}
    assert _ops("gta6.research.semantic-synthesis") == {
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }
    assert {
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }.issubset(_ops("editorial.process"))
    assert {
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }.issubset(_ops("youtube.department.script-review"))
    assert _ops("production.plan") == {
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }
    assert _ops("production.render.execute") == {
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }


def test_deterministic_collection_is_not_semantic_but_synthesis_is():
    collection = derive_required_operations({
        "task_id": "research-collect",
        "task_class": "evidence-collection",
        "objective": "collect fresh evidence from current GTA6 official sources",
        "required_capability_description": "fresh evidence collection",
        "expected_output": "source packet",
        "acceptance_criteria": ["fresh official evidence"],
        "dependencies": [],
    })
    assert set(collection) == {CAN_PRODUCE_ARTIFACT_REFS}

    synthesis = derive_required_operations({
        "task_id": "research-synthesize",
        "task_class": "research-synthesis",
        "objective": "analyze fresh evidence and synthesize the current editorial angle",
        "required_capability_description": "semantic research reasoning",
        "expected_output": "semantic research artifact",
        "acceptance_criteria": ["reason only from verified artifacts"],
        "dependencies": ["research-collect"],
    })
    assert set(synthesis) == {
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
        CAN_SEMANTIC_REASONING,
    }


def test_semantic_mission_contracts_accept_decomposition_and_reject_telegram_ingress():
    proposal = MissionPlanProposal(
        interpreted_goal="Produce a new current GTA6 video for private human review.",
        assumptions=(),
        required_outcomes=("fresh evidence", "professional review master"),
        tasks=(
            _task(
                "research-collect",
                "collect fresh evidence from current GTA6 official sources",
                "evidence-collection",
                "gta6.research",
                action="RESEARCH",
            ),
            _task(
                "research-synthesize",
                "analyze fresh evidence and synthesize the current editorial angle",
                "research-synthesis",
                "gta6.research.semantic-synthesis",
                action="RESEARCH",
                dependencies=("research-collect",),
            ),
            _task(
                "editorial-script",
                "produce the grounded editorial script",
                "editorial-production",
                "editorial.process",
                action="EDITORIAL",
                dependencies=("research-synthesize",),
            ),
            _task(
                "render-master",
                "render the professional master from persisted production artifacts",
                "professional-render",
                "production.render.execute",
                action="EXECUTION",
                dependencies=("editorial-script",),
                risk="EXTERNAL_SIDE_EFFECT",
            ),
            _task(
                "telegram-deliver",
                "deliver the human review package to Telegram",
                "human-review-delivery",
                "telegram.review.deliver",
                action="EXECUTION",
                dependencies=("editorial-script",),
                risk="EXTERNAL_SIDE_EFFECT",
            ),
        ),
        rationale=(
            "Separate deterministic evidence, semantic synthesis, production and "
            "outbound human review."
        ),
        context_usage_notes=(),
        uncertainty=0.1,
        needs_human_clarification=False,
    )
    assert proposal_registry_errors(proposal) == ()

    ingress = GLOBAL_CAPABILITY_REGISTRY.get("telegram.input.ingest")
    outbound = GLOBAL_CAPABILITY_REGISTRY.get("telegram.review.deliver")
    assert ingress is not None and ingress.domain == "telegram-ingress"
    assert outbound is not None and outbound.domain == "telegram-outbound"
    assert outbound.authority == "NONE"
    assert not set(ingress.execution_operations)
    assert _ops("telegram.review.deliver") == {
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }

    bad_task = _task(
        "telegram-deliver",
        "deliver the human review package to Telegram",
        "human-review-delivery",
        "telegram.input.ingest",
        action="EXECUTION",
        dependencies=("editorial-script",),
        risk="EXTERNAL_SIDE_EFFECT",
    )
    good_parent = _task(
        "editorial-script",
        "produce the grounded editorial script",
        "editorial-production",
        "editorial.process",
        action="EDITORIAL",
    )
    bad = MissionPlanProposal(
        interpreted_goal=proposal.interpreted_goal,
        assumptions=(),
        required_outcomes=proposal.required_outcomes,
        tasks=(good_parent, bad_task),
        rationale="invalid Telegram directionality fixture",
        context_usage_notes=(),
        uncertainty=0.1,
        needs_human_clarification=False,
    )
    errors = proposal_registry_errors(bad)
    assert any("telegram.input.ingest" in item for item in errors)


def test_editorial_action_is_normalized_from_task_semantics_not_agent_identity():
    proposal = MissionPlanProposal(
        interpreted_goal="Create an evidence-grounded GTA6 script.",
        assumptions=(),
        required_outcomes=("editorial script",),
        tasks=(
            MissionTaskProposal(
                task_id="script-work",
                objective=(
                    "Produce natural PT-BR script, ScriptSpec, ContentItem and "
                    "persisted ProductionPlan refs"
                ),
                task_class="editorial",
                required_capability_description=(
                    "editorial script generation from verified evidence"
                ),
                candidate_capability_ids=("editorial.process",),
                dependencies=("research-context",),
                expected_output=(
                    "PT-BR script + ScriptSpec + ContentItem + ProductionPlan refs"
                ),
                acceptance_criteria=("script_complete", "spec_valid"),
                risk_side_effect_class="READ_ONLY",
                action="DEVELOPMENT",
            ),
            MissionTaskProposal(
                task_id="research-context",
                objective="collect verified GTA6 context",
                task_class="research",
                required_capability_description="verified research context",
                candidate_capability_ids=("gta6.research.semantic-synthesis",),
                dependencies=(),
                expected_output="research artifact",
                acceptance_criteria=("evidence_grounded",),
                risk_side_effect_class="READ_ONLY",
                action="RESEARCH",
            ),
        ),
        rationale="Harness normalizes task action from semantics.",
        context_usage_notes=(),
        uncertainty=0.1,
        needs_human_clarification=False,
    )
    requirements = {
        item["task_id"]: item for item in proposal_requirements(proposal)
    }
    editorial = requirements["script-work"]
    assert editorial["declared_action"] == "DEVELOPMENT"
    assert editorial["action"] == "EDITORIAL"
    assert editorial["task_family"] == "EDITORIAL"


def test_provider_incident_diagnosis_uses_development_and_avoids_subject(monkeypatch):
    requirement = {
        "task_id": "classify-failure",
        "task_class": "semantic-synthesis",
        "action": "RESEARCH",
        "query": (
            "classify provider runtime failure from routing authorization and "
            "transport evidence; diagnose root cause and recovery"
        ),
        "objective": (
            "Classify the provider runtime failure and diagnose whether the "
            "provider call or transport started."
        ),
        "required_capability_description": (
            "provider runtime failure classification and recovery analysis"
        ),
        "candidate_capability_ids": ["gta6.research.semantic-synthesis"],
        "dependencies": ["collect-evidence"],
        "expected_output": "ProviderFailureClassification",
        "acceptance_criteria": ["classify failure from evidence"],
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "NOT_APPLICABLE",
        "required_operations": [
            CAN_SEMANTIC_REASONING,
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        ],
    }
    monkeypatch.setattr(
        adaptive_planning,
        "_profiled_registry_discover",
        lambda **kwargs: [
            {"capability_id": "gta6.research.semantic-synthesis"},
            {"capability_id": "addy:debugging-and-error-recovery"},
        ],
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_profiled_capability_health",
        lambda capability_id: SimpleNamespace(
            to_dict=lambda: {
                "capability_id": capability_id,
                "state": "HEALTHY",
                "reason": "incident routing proof",
            }
        ),
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_capability_failure_memory",
        lambda capability_id, context: None,
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_competence_score",
        lambda record, requirement, context: (0.0, False, None),
    )

    selected, _, avoided, evidence = select_capability_for_requirement(
        requirement,
        context={
            "mission_class": "SYSTEM_IMPROVEMENT",
            "canonical_state": {
                "incident": {
                    "capability_id": "gta6.research.semantic-synthesis",
                }
            },
        },
        used=set(),
    )

    assert evidence["declared_action"] == "RESEARCH"
    assert evidence["effective_action"] == "DEVELOPMENT"
    assert evidence["task_family"] == "DEVELOPMENT"
    assert selected == "addy:debugging-and-error-recovery"
    assert (
        "gta6.research.semantic-synthesis:"
        "incident-subject-cannot-self-diagnose"
    ) in avoided


def test_system_incident_independent_review_normalizes_to_development():
    proposal = MissionPlanProposal(
        interpreted_goal="Recover from a real provider runtime incident.",
        assumptions=(),
        required_outcomes=("reviewed recovery strategy",),
        tasks=(
            MissionTaskProposal(
                task_id="independent-review",
                objective=(
                    "Independently review the diagnosis and proposed recovery "
                    "using the supplied evidence artifact."
                ),
                task_class="independent-review",
                required_capability_description=(
                    "independent review over supplied evidence"
                ),
                candidate_capability_ids=(),
                dependencies=("recovery-proposal",),
                expected_output="independent review verdict",
                acceptance_criteria=("review evidence and recovery safety",),
                risk_side_effect_class="READ_ONLY",
                action="RESEARCH",
            ),
        ),
        rationale="Review is system/runtime governance, not research collection.",
        context_usage_notes=(),
        uncertainty=0.1,
        needs_human_clarification=False,
    )
    requirement = proposal_requirements(proposal)[0]
    assert requirement["declared_action"] == "RESEARCH"
    assert requirement["task_family"] == "DEVELOPMENT"
    assert requirement["action"] == "DEVELOPMENT"


def test_editorial_registry_selection_rejects_development_addy_skill(monkeypatch):
    requirement = {
        "task_id": "script-work",
        "task_class": "editorial",
        "action": "DEVELOPMENT",
        "declared_action": "DEVELOPMENT",
        "query": (
            "editorial script generation natural PT-BR ScriptSpec ContentItem "
            "ProductionPlan refs"
        ),
        "objective": "Produce natural PT-BR editorial script from verified evidence",
        "required_capability_description": "editorial script generation",
        "candidate_capability_ids": [],
        "dependencies": ["research-context"],
        "expected_output": (
            "PT-BR script + ScriptSpec + ContentItem + ProductionPlan artifact refs"
        ),
        "acceptance_criteria": ["script_complete", "spec_valid"],
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "NOT_APPLICABLE",
        "required_operations": [
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        ],
    }
    monkeypatch.setattr(
        adaptive_planning,
        "_profiled_registry_discover",
        lambda **_: [
            {"capability_id": "addy:api-and-interface-design"},
            {"capability_id": "editorial.process"},
        ],
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_profiled_capability_health",
        lambda capability_id: SimpleNamespace(
            to_dict=lambda: {
                "capability_id": capability_id,
                "state": "HEALTHY",
                "reason": "focused selection proof",
            }
        ),
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_capability_failure_memory",
        lambda capability_id, context: None,
    )
    monkeypatch.setattr(
        adaptive_planning,
        "_competence_score",
        lambda record, requirement, context: (0.0, False, None),
    )

    selected, _, avoided, evidence = select_capability_for_requirement(
        requirement,
        context={"mission_class": "GTA6_INTELLIGENCE"},
        used=set(),
    )

    assert selected == "editorial.process"
    assert evidence["effective_action"] == "EDITORIAL"
    assert evidence["task_family"] == "EDITORIAL"
    assert evidence["selected_domain"] == "editorial"
    assert any(
        item.startswith(
            "addy:api-and-interface-design:task-domain-incompatible:"
        )
        for item in avoided
    )
    assert all(
        item["capability_id"] != "addy:api-and-interface-design"
        for item in evidence["top_candidates"]
    )


def test_production_plan_consumes_direct_artifact_and_produces_persisted_ref(monkeypatch):
    import app.services.native_capability_adapters as native

    parent_result = {
        "content_item": {
            "id": 17,
            "script_id": 8,
            "idea_id": 4,
            "objective": "new GTA6 evidence",
            "format": "long-form",
            "estimated_duration_seconds": 600.0,
            "narrative_blocks": [
                {"heading": "Contexto", "content": "Texto factual."}
            ],
            "visual_requirements": [],
        }
    }
    context = {
        "parent_handoffs": [{
            "task_id": "editorial-script",
            "direct_dependency": True,
            "task_result_ref": "artifact:task-results/editorial-script-0.json",
            "content_sha256": "a" * 64,
            "result": parent_result,
            "output_artifact_refs": ["content-item:17"],
            "evidence_refs": [
                "research-semantic:mission:research-synthesize"
            ],
        }]
    }
    monkeypatch.setattr(
        native,
        "get_production_plan_by_content_item_id",
        lambda _: None,
    )
    monkeypatch.setattr(
        native,
        "create_production_plan",
        lambda item: {
            "content_item_id": item["id"],
            "scenes": [{"order": 1}],
        },
    )
    monkeypatch.setattr(
        native,
        "insert_production_plan",
        lambda **_: 44,
    )

    capability = SimpleNamespace(
        capability_id="production.plan",
        executor_binding=native.BINDINGS["production.plan"],
    )
    result = execute_production_plan_capability(
        capability,
        {"context": context},
    )
    assert result["artifact_ref"] == "production-plan:44"
    assert result["input_refs"] == [
        "artifact:task-results/editorial-script-0.json"
    ]
    assert result["direct_lineage_preserved"] is True

    envelope = build_task_result_envelope(
        mission_id="mission-contract-proof",
        task_id="production-plan",
        capability_id="production.plan",
        agent_id=None,
        skill_id="gta6-production",
        executor_binding=native.BINDINGS["production.plan"],
        status="COMPLETED",
        started_at="2026-09-23T00:00:00+00:00",
        completed_at="2026-09-23T00:00:01+00:00",
        elapsed_ms=1000.0,
        result=result,
        source_task_ids=("editorial-script",),
        authorization_id="auth-contract-proof",
    )
    assert "production-plan:44" in envelope.output_artifact_refs
    assert (
        "artifact:task-results/editorial-script-0.json"
        in envelope.evidence_refs
    )
    assert envelope.source_task_ids == ("editorial-script",)



def test_semantic_incident_tasks_require_semantic_reasoning_but_collection_does_not():
    collection = derive_required_operations({
        "task_id": "collect-evidence",
        "task_class": "evidence-collection",
        "objective": "extrair e normalizar evidências brutas já materializadas",
        "required_capability_description": "artifact evidence collection",
        "expected_output": "incident evidence packet",
        "acceptance_criteria": ["preserve lineage"],
        "dependencies": [],
    })
    assert set(collection) == {CAN_PRODUCE_ARTIFACT_REFS}

    diagnosis = derive_required_operations({
        "task_id": "agent-diagnosis",
        "task_class": "semantic",
        "objective": "Diagnosticar a causa raiz do incidente observado",
        "required_capability_description": "diagnóstico semântico de runtime",
        "expected_output": "DIAGNOSIS_ARTIFACT",
        "acceptance_criteria": ["causa raiz sustentada por evidência"],
        "dependencies": ["collect-evidence"],
    })
    assert {
        CAN_SEMANTIC_REASONING,
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }.issubset(set(diagnosis))

def test_production_semantic_contract_rejects_planner_capability_swaps():
    editorial = MissionTaskProposal(
        task_id="editorial-script",
        objective=(
            "Produce a natural PT-BR script with ScriptSpec and ContentItem "
            "for the verified topic"
        ),
        task_class="editorial",
        required_capability_description=(
            "PT-BR script + ScriptSpec + ContentItem ready for production planning"
        ),
        candidate_capability_ids=("youtube.department.script-review",),
        dependencies=("fact-verification",),
        expected_output="/artifacts/editorial_script.json",
        acceptance_criteria=("script_complete",),
        risk_side_effect_class="READ_ONLY",
        action="EDITORIAL",
    )
    assert not adaptive_planning._candidate_hint_is_hard_compatible(
        editorial,
        "youtube.department.script-review",
    )
    assert adaptive_planning._candidate_hint_is_hard_compatible(
        editorial,
        "editorial.process",
    )

    current_research = MissionTaskProposal(
        task_id="topic-selection",
        objective=(
            "Select a current high-relevance GTA 6 topic with verified fresh evidence"
        ),
        task_class="evidence-collection",
        required_capability_description=(
            "current GTA 6 topic with verified sources and novelty score"
        ),
        candidate_capability_ids=("gta6.knowledge.retrieve",),
        dependencies=(),
        expected_output="/artifacts/topic_selection.json",
        acceptance_criteria=("fresh official evidence",),
        risk_side_effect_class="READ_ONLY",
        action="RESEARCH",
    )
    assert not adaptive_planning._candidate_hint_is_hard_compatible(
        current_research,
        "gta6.knowledge.retrieve",
    )
    assert adaptive_planning._candidate_hint_is_hard_compatible(
        current_research,
        "gta6.research",
    )

    script_review = MissionTaskProposal(
        task_id="script-review",
        objective="YouTube specialist review for retention, pacing, and policy compliance",
        task_class="review",
        required_capability_description=(
            "YouTube specialist review with recommendations and limitations"
        ),
        candidate_capability_ids=("youtube.department.content-strategy",),
        dependencies=("editorial-script",),
        expected_output="/artifacts/script_review.json",
        acceptance_criteria=("review_complete",),
        risk_side_effect_class="READ_ONLY",
        action="EDITORIAL",
    )
    assert not adaptive_planning._candidate_hint_is_hard_compatible(
        script_review,
        "youtube.department.content-strategy",
    )
    assert adaptive_planning._candidate_hint_is_hard_compatible(
        script_review,
        "youtube.department.script-review",
    )

    master = MissionTaskProposal(
        task_id="master-production",
        objective=(
            "Execute audiovisual production to generate MASTER_FINAL "
            "1920x1080 with QA"
        ),
        task_class="execution",
        required_capability_description="MASTER_FINAL artifact with QA evidence",
        candidate_capability_ids=("youtube.department.production-management",),
        dependencies=("production-plan",),
        expected_output="/artifacts/master_final.json",
        acceptance_criteria=("master_qc",),
        risk_side_effect_class="READ_ONLY",
        action="EXECUTION",
    )
    assert not adaptive_planning._candidate_hint_is_hard_compatible(
        master,
        "youtube.department.production-management",
    )
    assert adaptive_planning._candidate_hint_is_hard_compatible(
        master,
        "production.render.execute",
    )

def test_youtube_script_review_is_registered_as_semantic_reasoner():
    record = GLOBAL_CAPABILITY_REGISTRY.get("youtube.department.script-review")
    assert record is not None
    assert record.resolved_execution_kind == "SEMANTIC_REASONER"
    assert CAN_SEMANTIC_REASONING in set(record.execution_operations)

def test_youtube_semantic_context_is_bounded_without_losing_direct_lineage():
    context = _bounded_youtube_semantic_context(
        human_goal="produce a current GTA 6 private review video " + ("goal " * 1000),
        selected_topic={"title": "topic " * 1000, "score": 9.1},
        claims=[
            {
                "claim_id": f"claim-{index}",
                "statement": "verified statement " * 500,
                "source": "https://example.test/source/" + ("x" * 1200),
                "evidence_ref": f"artifact:claim-{index}.json",
            }
            for index in range(16)
        ],
        parent_context={
            "parent_handoffs": [
                {
                    "task_id": f"parent-{index}",
                    "capability_id": "editorial.process",
                    "task_result_ref": f"artifact:task-results/parent-{index}.json",
                    "content_sha256": "a" * 64,
                    "result_summary": "summary " * 1000,
                    "evidence_refs": [f"artifact:evidence-{index}.json"],
                    "direct_dependency": True,
                }
                for index in range(10)
            ]
        },
        script_text="script " * 6000,
    )
    encoded = __import__("json").dumps(
        context, ensure_ascii=False, sort_keys=True, default=str
    )
    assert len(encoded) <= 20_000
    assert context["parent_summaries"]
    assert context["parent_summaries"][0]["task_result_ref"].startswith("artifact:")
    assert context["evidence_map"]
    assert context["script"]


def test_professional_duration_target_never_drops_below_twenty_minutes():
    for claim_count in (1, 2, 3, 5, 8):
        assert _target_duration_seconds(claim_count) >= 1200.0
    assert _target_duration_seconds(1) == 1200.0
    assert _target_duration_seconds(2) == 1200.0
    assert _target_duration_seconds(3) == 1200.0
    assert _target_duration_seconds(5) == 1200.0
    assert _target_duration_seconds(8) == 1200.0
    assert _target_duration_seconds(12) == 1500.0


def test_longform_retry_reconciles_preferred_target_only_to_professional_minimum():
    assert _longform_retry_target_seconds(1500.0) == 1200.0
    assert _longform_retry_target_seconds(1200.0) == 1200.0
    assert _longform_retry_target_seconds(600.0) == 1200.0
    assert _longform_retry_target_seconds(None) == 1200.0


def test_web_acquisition_status_never_reports_pass_for_blocked_transports():
    assert _governed_web_acquisition_status(
        selected_count=2,
        successful_count=0,
        blocked_count=2,
    ) == "BLOCKED_ZERO_COST_TRANSPORT"
    assert _governed_web_acquisition_status(
        selected_count=2,
        successful_count=1,
        blocked_count=1,
    ) == "PASS"
    assert _governed_web_acquisition_status(
        selected_count=0,
        successful_count=0,
        blocked_count=0,
    ) == "NO_NEW_URLS"

def test_novelty_duration_uses_human_approved_voice_b_calibration(monkeypatch):
    assert VOICE_B_EFFECTIVE_PLANNING_WPM == 132.0
    assert PRE_TTS_DURATION_TOLERANCE_MINUTES == 0.35

    monkeypatch.setattr(
        "scripts.real_multi_agent_production.list_research_items",
        lambda: [],
    )
    monkeypatch.setattr(
        "scripts.real_multi_agent_production.list_scripts",
        lambda: [],
    )
    state = {
        "selected_topic": "GTA VI pauta nova",
        "script": {"content": " ".join(["palavra"] * 615)},
        "script_id": 1,
        "target_duration_seconds": 1200.0,
        "claims": [{"statement": "achado oficial"}],
        "topic_selection": {"research_item_id": 1},
    }

    gate = _novelty_gate(state)

    assert gate["duration_estimator_wpm"] == 132.0
    assert gate["duration_supported_without_filler"] is False
    assert gate["content_supported_duration_minutes"] > 4.6
    assert gate["status"] == "FAIL"

def test_longform_underdelivery_is_escalated_to_bounded_evidence_expansion():
    failure = DelegatedCapabilityFailure(
        task_id="editorial-script",
        capability_id="editorial.process",
        failure_mode="AIProviderError",
        retry_attempt=0,
        retry_allowed=True,
        requires_harness_replan=False,
    )
    provider_error = AIProviderError(
        "AI response cannot sustain requested long-form duration without padding."
    )
    failure.__cause__ = provider_error

    assert _is_longform_underdelivery_failure(failure) is True
    assert MAX_LONGFORM_EVIDENCE_EXPANSIONS == 1
    assert 1 <= MAX_LONGFORM_EXPANSION_FACT_CHECKS <= 6


def test_editorial_retry_payload_includes_verified_expansion_evidence():
    task = SimpleNamespace(
        mission_id="mission-longform-recovery",
        task_id="editorial-script",
        goal_id="goal-longform-recovery",
        objective="produce a 20 minute factual script",
        capability_id="editorial.process",
        input_refs=(),
    )
    state = {
        "target_goal_id": "goal-longform-recovery",
        "target_duration_seconds": 1200.0,
        "selected_topic": "GTA VI pauta atual",
        "claims": [{
            "claim_id": "new-1",
            "statement": "Novo achado verificado",
            "source": "https://www.rockstargames.com/newswire",
            "fact_check_result": "SUPPORTED",
        }],
        "specialist_outputs": {},
        "expansion_evidence_refs": [
            "artifact:longform-expansion/research.json",
            "artifact:longform-expansion/fact-check.json",
        ],
    }
    parent_context = {
        "evidence_refs": ["artifact:original-knowledge.json"],
        "parent_handoffs": [],
    }

    payload = _payload_for_task(
        task=task,
        parent_context=parent_context,
        state=state,
        human_goal="produzir vídeo GTA 6 para revisão privada",
    )

    assert payload["target_duration_seconds"] == 1200.0
    assert (
        "artifact:longform-expansion/research.json"
        in payload["evidence_refs"]
    )
    assert (
        "artifact:longform-expansion/fact-check.json"
        in payload["editorial_context"]["content_strategy_evidence_refs"]
    )
    assert payload["editorial_context"]["verified_claims"][0][
        "fact_check_result"
    ] == "SUPPORTED"

def test_fresh_research_candidates_keep_source_provenance_and_drop_html_shell():
    evidence = {
        "artifact_ref": "github-actions:999",
        "packet": {
            "official_sources": [
                {
                    "url": "https://www.rockstargames.com/VI",
                    "resolved_url": "https://www.rockstargames.com/VI",
                    "content_excerpt": (
                        "Coming November 19, 2026. Jason and Lucia. "
                        "Vice City, Leonida."
                    ),
                },
                {
                    "url": "https://www.rockstargames.com/newswire",
                    "content_excerpt": "<!DOCTYPE html><html><head>shell</head></html>",
                },
            ],
            "secondary_sources": [
                {
                    "url": "https://example.test/current-gta6-report",
                    "title": "Current GTA VI report",
                    "summary": "Source-grounded secondary detail.",
                }
            ],
        },
    }

    candidates = _fresh_research_candidates(evidence, known_ids=set())

    assert len(candidates) == 2
    official = next(
        item for item in candidates
        if item["source"].startswith("https://www.rockstargames.com/")
    )
    secondary = next(
        item for item in candidates
        if item["source"].startswith("https://example.test/")
    )
    assert official["verification_status"] == "VERIFIED"
    assert official["fact_check_result"] == "OFFICIAL_PRIMARY"
    assert "github-actions:999" in official["evidence_refs"]
    assert secondary["verification_status"] == "PENDING"
    assert secondary["fact_check_result"] == "PENDING_FACT_CHECK"
    assert all(
        "<!doctype" not in item["statement"].casefold()
        for item in candidates
    )


def test_fresh_research_candidates_deduplicate_known_claim_ids():
    source = {
        "url": "https://www.rockstargames.com/VI",
        "content_excerpt": "Coming November 19, 2026.",
    }
    first = _fresh_research_candidates(
        {
            "artifact_ref": "github-actions:1",
            "packet": {"official_sources": [source]},
        },
        known_ids=set(),
    )
    assert len(first) == 1
    second = _fresh_research_candidates(
        {
            "artifact_ref": "github-actions:2",
            "packet": {"official_sources": [source]},
        },
        known_ids={first[0]["claim_id"]},
    )
    assert second == []

def test_longform_web_gap_budget_reserves_sources_without_expanding_child_budget():
    assert MAX_LONGFORM_RECOVERY_CHILD_TASKS == 8
    assert MAX_LONGFORM_WEB_SOURCE_ACQUISITIONS == 2
    assert MAX_LONGFORM_WEB_EVIDENCE_SNAPSHOTS == 1

    full = [
        {
            "claim_id": f"official-{index}",
            "fact_check_result": "OFFICIAL_PRIMARY",
        }
        for index in range(MAX_LONGFORM_EXPANSION_FACT_CHECKS)
    ]
    # A real long-form underdelivery already proved that the ordinary evidence
    # base needs diversification; reserve two governed source acquisitions.
    assert _web_acquisition_slots(full) == 2

    pending = [
        {
            "claim_id": f"secondary-{index}",
            "fact_check_result": "PENDING_FACT_CHECK",
        }
        for index in range(MAX_LONGFORM_EXPANSION_FACT_CHECKS)
    ]
    # With two fresh secondary checks, reserve one explicit snapshot and keep
    # the unchanged eight-child ceiling. One source/fact-check pair still fits.
    assert _web_acquisition_slots(pending) == 1


def test_web_failure_taxonomy_matches_nightly_recovery_contract():
    assert _classify_web_failure(
        RuntimeError("APILAYER_API_KEY_REQUIRED")
    ) == "AUTHENTICATION"
    assert _classify_web_failure(
        RuntimeError("APILAYER_SUBSCRIPTION_REQUIRED")
    ) == "API_SUBSCRIPTION_REQUIRED"
    assert _classify_web_failure(
        RuntimeError("FREE_QUOTA_EXHAUSTED")
    ) == "FREE_QUOTA_EXHAUSTED"
    assert _classify_web_failure(
        RuntimeError("APILAYER_ENDPOINT_REQUEST_CONTRACT_FAILED")
    ) == "ENDPOINT_REQUEST_CONTRACT"
    assert _classify_web_failure(
        RuntimeError("APILAYER_TRANSPORT_FAILED")
    ) == "TRANSPORT"
    assert _classify_web_failure(
        RuntimeError("APILAYER_SEARCH_NORMALIZATION_FAILED")
    ) == "NORMALIZATION"
    assert _classify_web_failure(
        PermissionError("web acquisition capability routing mismatch")
    ) == "HARNESS_AUTHORIZATION"
    assert _classify_web_failure(
        RuntimeError("WEB_PROVENANCE_INVALID:source_acquisition")
    ) == "PROVENANCE"


def test_longform_web_gap_allows_two_governed_sources_after_official_research():
    candidates = [
        {
            "claim_id": f"official-{index}",
            "fact_check_result": "OFFICIAL_PRIMARY",
        }
        for index in range(3)
    ]
    assert _web_acquisition_slots(candidates) == 2

def test_web_source_statement_strips_script_shell_and_returns_grounded_sentence():
    acquired = {
        "content": (
            "<!doctype html><html><head><style>body{display:none}</style>"
            "<script>window.noise = 'GTA 6 fake shell';</script></head><body>"
            "<nav>Navigation noise</nav>"
            "<article><h1>GTA 6 collector set details</h1>"
            "<p>The GTA 6 collector set costs $400 and does not include the game itself.</p>"
            "<p>Rockstar says Grand Theft Auto VI launches separately.</p>"
            "</article></body></html>"
        )
    }

    statement = _web_source_statement(
        acquired,
        selected_topic="GTA 6 $400 Collector's Edition",
    )

    lowered = statement.casefold()
    assert "window.noise" not in lowered
    assert "body{display:none}" not in lowered
    assert "costs $400" in lowered
    assert "does not include the game" in lowered

def test_fresh_official_source_expands_into_distinct_atomic_findings():
    evidence = {
        "artifact_ref": "github-actions:official-longform",
        "packet": {
            "official_sources": [{
                "resolved_url": "https://www.rockstargames.com/VI",
                "content_excerpt": (
                    "Coming November 19, 2026. "
                    "An Extended Look is now playing with new GTA VI material. "
                    "The Vintage Vice City Pack is a pre-order bonus inspired by classic Vice City. "
                    "The Vice City Collection is a limited-edition collectible set inspired by Macca the Gator. "
                    "Jason and Lucia are caught in a criminal conspiracy across Leonida. "
                    "Grand Theft Auto VI: The Album features 34 original tracks for Vice City and Leonida."
                ),
            }],
            "secondary_sources": [],
        },
    }

    candidates = _fresh_research_candidates(evidence, known_ids=set())

    assert len(candidates) >= 5
    assert len({item["claim_id"] for item in candidates}) == len(candidates)
    assert all(item["fact_check_result"] == "OFFICIAL_PRIMARY" for item in candidates)
    assert any("34 original tracks" in item["statement"] for item in candidates)
    assert any("criminal conspiracy" in item["statement"] for item in candidates)


def test_longform_fallback_prefers_new_independent_source_families():
    selected = [{
        "source": "https://www.rockstargames.com/VI",
        "fact_check_result": "OFFICIAL_PRIMARY",
    }]
    fresh = {
        "packet": {
            "official_sources": [
                {"resolved_url": "https://store.rockstargames.com/game/buy-gta-vi"},
            ],
            "secondary_sources": [
                {"url": "https://me.ign.com/ar/grand-theft-auto-vi/first"},
                {"url": "https://me.ign.com/ar/grand-theft-auto-vi/second"},
                {"url": "https://www.gamespot.com/articles/gta-6-current-report/"},
                {"url": "https://www.reddit.com/r/GTA6/comments/current/"},
            ],
        }
    }

    urls = _longform_fallback_source_urls(
        selected,
        fresh,
        excluded_source_urls=["https://www.rockstargames.com/VI"],
    )

    assert urls[0].startswith("https://me.ign.com/")
    assert urls[1].startswith("https://www.gamespot.com/")
    assert urls[2].startswith("https://www.reddit.com/")
    assert "store.rockstargames.com" in urls[3]
    assert urls[-1].endswith("/second")

def test_official_longform_findings_do_not_consume_secondary_fact_check_budget():
    official = [
        {
            "claim_id": f"official-{index}",
            "fact_check_result": "OFFICIAL_PRIMARY",
        }
        for index in range(12)
    ]
    secondary = [
        {
            "claim_id": f"secondary-{index}",
            "fact_check_result": "PENDING_FACT_CHECK",
        }
        for index in range(8)
    ]

    selected_official, selected_pending = _partition_longform_fresh_candidates(
        [*official, *secondary]
    )

    assert len(selected_official) == 12
    assert len(selected_pending) == 2
    assert all(
        item["fact_check_result"] == "OFFICIAL_PRIMARY"
        for item in selected_official
    )
    assert all(
        item["fact_check_result"] == "PENDING_FACT_CHECK"
        for item in selected_pending
    )

def test_dependent_knowledge_retrieval_keeps_deterministic_candidate_eligible():
    requirement = {
        "task_id": "knowledge-context-after-research",
        "task_class": "knowledge-retrieval",
        "functional_role": "GENERAL",
        "action": "RESEARCH",
        "query": "bounded contextual background from persisted research",
        "objective": "retrieve bounded canonical context from the selected topic",
        "required_capability_description": "bounded canonical context",
        "candidate_capability_ids": ["gta6.knowledge.retrieve"],
        "dependencies": ["research-topic"],
        "required_operations": [
            CAN_CONSUME_ARTIFACT_REFS,
            CAN_PRODUCE_ARTIFACT_REFS,
        ],
        "expected_output": "bounded knowledge context with provenance",
        "acceptance_criteria": ["bounded context", "preserve provenance"],
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "OPTIONAL_HINTS",
    }

    selected, _, avoided, evidence = select_capability_for_requirement(
        requirement,
        context={"mission_class": "GTA6_INTELLIGENCE"},
        used=set(),
    )

    assert selected == "gta6.knowledge.retrieve"
    assert evidence["effective_action"] == "RESEARCH"
    assert not any(
        item.startswith(
            "gta6.knowledge.retrieve:execution-contract-insufficient"
        )
        for item in avoided
    )


def test_knowledge_retrieval_without_candidate_hint_discovers_canonical_gta6_retriever():
    requirement = {
        "task_id": "knowledge-context",
        "task_class": "knowledge-retrieval",
        "functional_role": "GENERAL",
        "action": "RESEARCH",
        "query": "bounded contextual background for the selected GTA VI topic",
        "objective": "retrieve bounded canonical context for the selected topic",
        "required_capability_description": "bounded canonical context",
        "candidate_capability_ids": [],
        "dependencies": [],
        "expected_output": "bounded knowledge context with provenance",
        "acceptance_criteria": ["bounded context", "preserve provenance"],
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "NOT_APPLICABLE",
    }

    selected, _, avoided, evidence = select_capability_for_requirement(
        requirement,
        context={"mission_class": "GTA6_INTELLIGENCE"},
        used=set(),
    )

    assert selected == "gta6.knowledge.retrieve"
    assert evidence["effective_action"] == "RESEARCH"
    assert evidence["task_family"] == "RESEARCH"
    assert any(
        item.startswith("knowledge.retrieve:task-adapter-incompatible")
        or item.startswith("knowledge.retrieve:missing-")
        for item in avoided
    )


def test_longform_recovery_cannot_pass_with_blocked_required_web_discovery():
    outcome = _longform_recovery_gate_outcome(
        verified_count=7,
        web_recovery={
            "WEB_DISCOVERY_GOVERNED": "BLOCKED_API_SUBSCRIPTION_REQUIRED",
            "web_discovery_failure_class": "API_SUBSCRIPTION_REQUIRED",
            "WEB_SOURCE_ACQUISITION_GOVERNED": "PASS",
            "PROVENANCE": "PASS",
        },
    )

    assert outcome["status"] == "BLOCKED"
    assert outcome["external_blocker"] == "API_SUBSCRIPTION_REQUIRED"
    assert outcome["failed_gates"] == ["WEB_DISCOVERY_GOVERNED"]


def test_longform_recovery_requires_every_phase2_gate_before_pass():
    outcome = _longform_recovery_gate_outcome(
        verified_count=4,
        web_recovery={
            "WEB_DISCOVERY_GOVERNED": "PASS",
            "WEB_SOURCE_ACQUISITION_GOVERNED": "PASS",
            "PROVENANCE": "PASS",
        },
    )

    assert outcome["status"] == "PASS"
    assert outcome["failed_gates"] == []
    assert outcome["external_blocker"] is None


def test_longform_external_web_blocker_is_reported_without_masking_as_insufficient():
    error = _longform_expansion_terminal_error({
        "status": "BLOCKED",
        "failure_class": "API_SUBSCRIPTION_REQUIRED",
        "external_blocker": "API_SUBSCRIPTION_REQUIRED",
    })

    assert error == "API_SUBSCRIPTION_REQUIRED:WEB_DISCOVERY_GOVERNED"
