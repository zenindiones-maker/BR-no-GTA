from __future__ import annotations

import json

import pytest

from app.services.capability_execution_contract_service import (
    CAN_CONSUME_ARTIFACT_REFS,
    CAN_PRODUCE_ARTIFACT_REFS,
    EFFECT_HUMAN_MESSAGE_DELIVERY,
    OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1,
    SURFACE_TELEGRAM_GROUP,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_adaptive_planning_service import proposal_requirements
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    MissionTaskProposal,
)
from app.services.typed_task_requirement_service import (
    TYPED_TASK_REQUIREMENT_SCHEMA,
    TypedTaskRequirement,
    contract_information_retention_rate,
)


PRODUCT_DIGEST = "sha256:" + "1" * 64


def _historical_telegram_proposal() -> MissionPlanProposal:
    return MissionPlanProposal(
        interpreted_goal="Deliver private review artifacts",
        assumptions=(),
        required_outcomes=("human private review delivery",),
        tasks=(
            MissionTaskProposal(
                task_id="telegram_deliver",
                objective=(
                    "Deliver script, plan, and review instructions via "
                    "Telegram for human private review"
                ),
                task_class="presentation",
                required_capability_description="",
                candidate_capability_ids=("telegram.review.deliver",),
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
        rationale="Historical Telegram delivery proposal.",
        context_usage_notes=(),
        uncertainty=0.1,
        needs_human_clarification=False,
    )


def test_historical_telegram_requirement_retains_effect_surface_output_and_risk():
    requirement = proposal_requirements(
        _historical_telegram_proposal(),
        product_contract_digest=PRODUCT_DIGEST,
    )[0]
    assert requirement["schema"] == TYPED_TASK_REQUIREMENT_SCHEMA
    assert requirement["action"] == "EXECUTION"
    assert requirement["task_class"] == "presentation"
    assert requirement["functional_role"] == "PRESENTATION"
    assert requirement["required_execution_kind"] == "PRESENTATION"
    assert set(requirement["required_operations"]) == {
        CAN_CONSUME_ARTIFACT_REFS,
        CAN_PRODUCE_ARTIFACT_REFS,
    }
    assert requirement["required_effects"] == [
        EFFECT_HUMAN_MESSAGE_DELIVERY
    ]
    assert requirement["required_surfaces"] == [SURFACE_TELEGRAM_GROUP]
    assert requirement["required_output_contract_ids"] == [
        OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1
    ]
    assert requirement["risk_level"] == "LOW"
    assert requirement["required_side_effect_class"] == "EXTERNAL_SIDE_EFFECT"
    assert requirement["risk_side_effect_class"] == "EXTERNAL_SIDE_EFFECT"
    assert requirement["required_domain"] == "telegram-outbound"
    assert requirement["required_domain_family"] == "telegram"
    assert requirement["product_contract_digest"] == PRODUCT_DIGEST
    assert requirement["proposal_candidate_hints"] == [
        "telegram.review.deliver"
    ]
    assert requirement["requirement_digest"].startswith("sha256:")


def test_typed_requirement_roundtrip_retains_all_mandatory_semantics():
    raw = proposal_requirements(
        _historical_telegram_proposal(),
        product_contract_digest=PRODUCT_DIGEST,
    )[0]
    typed = TypedTaskRequirement.from_mapping(raw)
    reloaded = TypedTaskRequirement.from_mapping(
        json.loads(json.dumps(typed.to_dict(), sort_keys=True))
    )
    assert typed == reloaded
    assert typed.digest() == reloaded.digest()
    assert isinstance(typed.to_dict()["required_effects"], list)
    assert isinstance(typed.to_dict()["required_surfaces"], list)
    assert isinstance(typed.to_dict()["required_output_contract_ids"], list)
    assert contract_information_retention_rate(typed, reloaded) == 100.0


def test_external_required_effect_cannot_silently_become_read_only():
    raw = proposal_requirements(
        _historical_telegram_proposal(),
        product_contract_digest=PRODUCT_DIGEST,
    )[0]
    raw["required_side_effect_class"] = "READ_ONLY"
    with pytest.raises(
        ValueError,
        match="REQUIRED_EFFECT_CANNOT_BE_MATERIALIZED_AS_READ_ONLY",
    ):
        TypedTaskRequirement.from_mapping(raw)


def test_general_role_cannot_erase_explicit_external_contract():
    raw = proposal_requirements(
        _historical_telegram_proposal(),
        product_contract_digest=PRODUCT_DIGEST,
    )[0]
    raw["functional_role"] = "GENERAL"
    typed = TypedTaskRequirement.from_mapping(raw)
    assert typed.functional_role == "GENERAL"
    assert typed.required_effects == (EFFECT_HUMAN_MESSAGE_DELIVERY,)
    assert typed.required_surfaces == (SURFACE_TELEGRAM_GROUP,)
    assert typed.required_output_contract_ids == (
        OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1,
    )
    assert typed.required_side_effect_class == "EXTERNAL_SIDE_EFFECT"


def test_registry_declares_same_typed_telegram_contract():
    record = GLOBAL_CAPABILITY_REGISTRY.get("telegram.review.deliver")
    assert record is not None
    assert record.side_effect_class == "EXTERNAL_SIDE_EFFECT"
    assert record.execution_effects == (EFFECT_HUMAN_MESSAGE_DELIVERY,)
    assert record.execution_surfaces == (SURFACE_TELEGRAM_GROUP,)
    assert record.output_contract_ids == (
        OUTPUT_CONTRACT_TELEGRAM_DELIVERY_RECEIPT_V1,
    )
    assert record.functional_roles == ("PRESENTATION",)
    assert record.resolved_execution_kind == "PRESENTATION"


def test_dynamic_youtube_specialist_has_non_telegram_typed_output_contract():
    record = GLOBAL_CAPABILITY_REGISTRY.get(
        "youtube.department.analytics-analysis"
    )
    assert record is not None
    assert record.execution_effects == ()
    assert record.execution_surfaces == ()
    assert record.output_contract_ids == ("YouTubeSpecialistResult/v1",)
