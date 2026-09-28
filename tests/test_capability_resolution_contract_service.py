from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import app.services.harness_adaptive_planning_service as adaptive_service
from app.services.capability_execution_contract_service import (
    EFFECT_HUMAN_MESSAGE_DELIVERY,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_adaptive_planning_service import (
    proposal_requirements,
    select_capability_for_requirement,
)
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    MissionTaskProposal,
)


PRODUCT_DIGEST = "sha256:" + "2" * 64


def _historical_363710_proposal() -> MissionPlanProposal:
    return MissionPlanProposal(
        interpreted_goal="Produce private BR-no-GTA review artifacts",
        assumptions=(),
        required_outcomes=("private human review",),
        tasks=(
            MissionTaskProposal(
                task_id="research_topic",
                objective=(
                    "Identify a fresh, high-relevance GTA 6 topic with "
                    "verifiable primary sources from the last 30 days"
                ),
                task_class="fresh-evidence-collection",
                required_capability_description=(
                    "Identify a fresh, high-relevance GTA 6 topic with "
                    "verifiable primary sources from the last 30 days "
                    "topic has >=3 primary sources topic is Brazil-relevant"
                ),
                candidate_capability_ids=("gta6.research",),
                dependencies=(),
                expected_output="topic_brief + source_refs",
                acceptance_criteria=(
                    "topic has >=3 primary sources",
                    "topic is Brazil-relevant",
                ),
                risk_side_effect_class="READ_ONLY",
                action="RESEARCH",
            ),
            MissionTaskProposal(
                task_id="fact_check",
                objective=(
                    "Verify all claims in topic_brief against authoritative "
                    "sources"
                ),
                task_class="fact-check",
                required_capability_description=(
                    "Verify all claims in topic_brief against authoritative "
                    "sources all claims verified or flagged no unverified "
                    "speculation"
                ),
                candidate_capability_ids=("gta6.fact-check",),
                dependencies=("research_topic",),
                expected_output="FactCheckResult + claim_evidence_map",
                acceptance_criteria=(
                    "all claims verified or flagged",
                    "no unverified speculation",
                ),
                risk_side_effect_class="READ_ONLY",
                action="RESEARCH",
            ),
            MissionTaskProposal(
                task_id="editorial_script",
                objective=(
                    "Produce natural PT-BR script + ScriptSpec + ContentItem "
                    "from verified topic_brief"
                ),
                task_class="editorial",
                required_capability_description=(
                    "Produce natural PT-BR script + ScriptSpec + ContentItem "
                    "from verified topic_brief script follows BR YouTube "
                    "conventions duration 8-12 min"
                ),
                candidate_capability_ids=("editorial.process",),
                dependencies=("fact_check",),
                expected_output=(
                    "script_artifact_ref + ScriptSpec + ContentItem"
                ),
                acceptance_criteria=(
                    "script follows BR YouTube conventions",
                    "duration 8-12 min",
                ),
                risk_side_effect_class="READ_ONLY",
                action="EDITORIAL",
            ),
            MissionTaskProposal(
                task_id="production_plan",
                objective=(
                    "Create ProductionPlan with scene breakdown, asset list, "
                    "and master spec (1920x1080@30 H264 AAC)"
                ),
                task_class="production-plan",
                required_capability_description=(
                    "Create ProductionPlan with scene breakdown, asset list, "
                    "and master spec (1920x1080@30 H264 AAC) plan matches "
                    "ScriptSpec assets scoped for private HD review"
                ),
                candidate_capability_ids=("production.plan",),
                dependencies=("editorial_script",),
                expected_output=(
                    "ProductionPlan_artifact_ref + scene_breakdown"
                ),
                acceptance_criteria=(
                    "plan matches ScriptSpec",
                    "assets scoped for private HD review",
                ),
                risk_side_effect_class="READ_ONLY",
                action="EDITORIAL",
            ),
            MissionTaskProposal(
                task_id="telegram_deliver",
                objective=(
                    "Deliver script, plan, and review instructions via "
                    "Telegram for human private review"
                ),
                task_class="presentation",
                required_capability_description=(
                    "Deliver script, plan, and review instructions via "
                    "Telegram for human private review human receives all "
                    "artifacts private review workflow initiated"
                ),
                # Historical routed artifact selected this wrong specialist.
                candidate_capability_ids=(
                    "youtube.department.analytics-analysis",
                ),
                dependencies=("production_plan",),
                expected_output="Telegram_SENT_receipt + message_refs",
                acceptance_criteria=(
                    "human receives all artifacts",
                    "private review workflow initiated",
                ),
                risk_side_effect_class="LOW",
                action="EXECUTION",
            ),
        ),
        rationale="Historical five-task production-plan replay.",
        context_usage_notes=(),
        uncertainty=0.1,
        needs_human_clarification=False,
    )


def _healthy_runtime(monkeypatch):
    monkeypatch.setattr(
        adaptive_service,
        "_profiled_capability_health",
        lambda capability_id: SimpleNamespace(
            to_dict=lambda: {
                "capability_id": capability_id,
                "state": "HEALTHY",
                "reason": "focused contract resolver proof",
            }
        ),
    )
    monkeypatch.setattr(
        adaptive_service,
        "_capability_failure_memory",
        lambda capability_id, context: None,
    )


def _telegram_requirement():
    requirements = proposal_requirements(
        _historical_363710_proposal(),
        product_contract_digest=PRODUCT_DIGEST,
    )
    return {
        item["task_id"]: item
        for item in requirements
    }["telegram_deliver"]


def test_historical_telegram_hard_filters_analytics_before_soft_ranking(
    monkeypatch,
):
    _healthy_runtime(monkeypatch)
    monkeypatch.setattr(
        adaptive_service,
        "_profiled_registry_discover",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "typed requirements must use canonical runtime Registry"
            )
        ),
    )
    competence_calls = []
    monkeypatch.setattr(
        adaptive_service,
        "_competence_score",
        lambda record, requirement, context: (
            competence_calls.append(record.capability_id) or 999.0,
            True,
            {"tested_cases": 999},
        ),
    )

    selected, competence_used, avoided, evidence = (
        select_capability_for_requirement(
            _telegram_requirement(),
            context={
                "mission_class": "GTA6_INTELLIGENCE",
                "relevant_failure_memories": [],
                "competence_evidence": [],
            },
            used=set(),
        )
    )

    assert selected == "telegram.review.deliver"
    assert competence_used is False
    assert competence_calls == []
    assert evidence["contract_valid_count"] == 1
    assert evidence["soft_ranking_executed"] is False

    receipt = evidence["capability_resolution_receipt"]
    assert receipt["schema"] == "CapabilityResolutionReceipt/v1"
    assert (
        receipt["candidate_partition_source"]
        == "CANONICAL_RUNTIME_REGISTRY"
    )
    assert receipt["selected_capability_id"] == "telegram.review.deliver"
    assert receipt["proposal_substituted"] is True
    assert receipt["proposal_preserved"] is False
    assert (
        receipt["selection_reason"]
        == "SINGLE_CONTRACT_VALID_CANDIDATE"
    )
    assert receipt["contract_valid_candidates"] == [
        "telegram.review.deliver"
    ]

    analytics = next(
        item
        for item in receipt["hard_rejected_candidates"]
        if item["capability_id"]
        == "youtube.department.analytics-analysis"
    )
    codes = {reason["code"] for reason in analytics["reasons"]}
    assert "EXECUTION_KIND_MISMATCH" in codes
    assert "REQUIRED_EFFECT_MISMATCH" in codes
    assert "SURFACE_MISMATCH" in codes
    assert "DOMAIN_MISMATCH" in codes
    assert "OUTPUT_CONTRACT_MISMATCH" in codes
    assert "SIDE_EFFECT_AUTHORIZATION_MISMATCH" in codes
    assert any(
        "youtube.department.analytics-analysis" in item
        for item in avoided
    )


def test_least_privilege_runs_only_after_required_effect_satisfaction(
    monkeypatch,
):
    _healthy_runtime(monkeypatch)
    requirement = _telegram_requirement()
    requirement["proposal_candidate_hints"] = []
    requirement["candidate_capability_ids"] = []

    canonical = GLOBAL_CAPABILITY_REGISTRY.get(
        "telegram.review.deliver"
    )
    assert canonical is not None
    excess = replace(
        canonical,
        capability_id="telegram.review.deliver.excess",
        execution_effects=(
            EFFECT_HUMAN_MESSAGE_DELIVERY,
            "UNNEEDED_EXTERNAL_EFFECT",
        ),
    )
    records = {
        canonical.capability_id: canonical,
        excess.capability_id: excess,
    }
    monkeypatch.setattr(
        adaptive_service,
        "_profiled_registry_all",
        lambda: tuple(records.values()),
    )
    monkeypatch.setattr(
        adaptive_service,
        "_profiled_registry_get",
        lambda capability_id: records.get(capability_id),
    )
    monkeypatch.setattr(
        adaptive_service,
        "_competence_score",
        lambda record, requirement, context: (0.0, False, None),
    )

    selected, _, _, evidence = select_capability_for_requirement(
        requirement,
        context={
            "mission_class": "GTA6_INTELLIGENCE",
            "relevant_failure_memories": [],
            "competence_evidence": [],
        },
        used=set(),
    )

    assert evidence["contract_valid_count"] == 2
    assert evidence["soft_ranking_executed"] is True
    assert selected == "telegram.review.deliver"
    ranked = evidence["capability_resolution_receipt"][
        "soft_ranked_candidates"
    ]
    assert ranked[0]["capability_id"] == "telegram.review.deliver"


def test_historical_five_task_replay_keeps_valid_work_and_reopens_telegram(
    monkeypatch,
):
    _healthy_runtime(monkeypatch)
    monkeypatch.setattr(
        adaptive_service,
        "_competence_score",
        lambda record, requirement, context: (0.0, False, None),
    )

    requirements = proposal_requirements(
        _historical_363710_proposal(),
        product_contract_digest=PRODUCT_DIGEST,
    )
    expected_valid = {
        "research_topic": "gta6.research",
        "fact_check": "gta6.fact-check",
        "editorial_script": "editorial.process",
        "production_plan": "production.plan",
    }
    observed = {}

    for requirement in requirements:
        selected, _, _, evidence = select_capability_for_requirement(
            requirement,
            context={
                "mission_class": "GTA6_INTELLIGENCE",
                "relevant_failure_memories": [],
                "competence_evidence": [],
            },
            used=set(),
        )
        receipt = evidence["capability_resolution_receipt"]
        observed[requirement["task_id"]] = selected
        assert selected in receipt["contract_valid_candidates"]
        if requirement["task_id"] in expected_valid:
            assert (
                expected_valid[requirement["task_id"]]
                in receipt["contract_valid_candidates"]
            )

    assert observed["telegram_deliver"] == "telegram.review.deliver"
