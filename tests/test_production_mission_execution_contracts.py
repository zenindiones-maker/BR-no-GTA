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
    assert _ops("gta6.knowledge.retrieve") == {CAN_PRODUCE_ARTIFACT_REFS}

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
