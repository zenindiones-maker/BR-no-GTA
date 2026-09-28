from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.harness_adaptive_planning_service import (
    build_semantic_planning_context,
    propose_validated_semantic_plan,
)
from app.services.human_review_quality_gate import (
    TARGET_MIN_SECONDS,
    TARGET_PREFERRED_MAX_SECONDS,
)
from app.services.mission_product_contract_service import (
    bounded_planner_product_contract_projection,
    materialize_br_no_gta_mission_product_contract,
    mission_product_contract_digest,
    validate_mission_plan_product_contract,
)
from app.services.pronunciation_service import DEFAULT_VOICE
from app.services.semantic_mission_planner_service import (
    MissionPlanProposal,
    MissionTaskProposal,
    SemanticPlannerResult,
    build_semantic_planner_prompt,
)


def _proposal_with_duration(text: str) -> MissionPlanProposal:
    return MissionPlanProposal(
        interpreted_goal="Produce bounded BR no GTA 6 preproduction",
        assumptions=(),
        required_outcomes=("source-grounded editorial",),
        tasks=(
            MissionTaskProposal(
                task_id="editorial_script",
                objective="Produce the verified PT-BR editorial script",
                task_class="editorial",
                required_capability_description="editorial processing",
                candidate_capability_ids=(),
                dependencies=(),
                expected_output="ScriptSpec + ContentItem",
                acceptance_criteria=(text,),
                risk_side_effect_class="LOW",
                action="EDITORIAL",
            ),
        ),
        rationale="Minimum sufficient bounded editorial plan.",
        context_usage_notes=(),
        uncertainty=0.1,
        needs_human_clarification=False,
    )


def _planner_context(contract: dict) -> dict:
    digest = mission_product_contract_digest(contract)
    return {
        "human_goal": "Produce a real BR no GTA 6 review video",
        "project": "BR-no-GTA",
        "subject": "real audiovisual production",
        "goal_id": "goal-product-contract-test",
        "mission_class": "GTA6_INTELLIGENCE",
        "canonical_state": {
            "mission_product_contract": contract,
            "product_contract_digest": digest,
        },
        "conversation_state": {},
        "mission_product_contract": contract,
        "product_contract_digest": digest,
        "bounded_memory_context": {},
        "recent_execution_history": [],
        "relevant_failure_memories": [],
        "human_feedback_decisions": [],
        "provider_health": {},
        "registry_summary": [],
        "competence_evidence": [],
        "resource_bounds": {"max_tasks_per_mission": 8},
        "known_bad_paths": [],
    }


def test_mission_product_contract_is_canonical_and_uses_existing_policy_sources():
    contract = materialize_br_no_gta_mission_product_contract()
    duration = contract["duration"]
    assert contract["schema"] == "MissionProductContract/v1"
    assert duration["minimum_final_duration_seconds"] == TARGET_MIN_SECONDS == 1200
    assert duration["target_final_duration_seconds"] == {
        "minimum": TARGET_MIN_SECONDS,
        "maximum": TARGET_PREFERRED_MAX_SECONDS,
    }
    assert duration["minimum_supported_editorial_duration_minutes"] == 20.0
    assert duration["artificial_padding_forbidden"] is True
    assert contract["narration"]["voice"] == DEFAULT_VOICE
    assert contract["master_profile"] == "1920x1080@30 H264 AAC"
    assert contract["human_review"]["primary_interface"] == "telegram"
    assert contract["human_review"]["youtube_review_privacy"] == "PRIVATE"
    assert contract["publication"]["public_release_allowed"] is False
    assert contract["publication"]["unlisted_release_allowed"] is False
    assert (
        contract["semantic_planning"]["boundary"]
        == "PREPRODUCTION_THROUGH_PRODUCTION_PLAN"
    )


def test_product_contract_digest_is_stable_and_changes_with_policy():
    contract = materialize_br_no_gta_mission_product_contract()
    first = mission_product_contract_digest(contract)
    second = mission_product_contract_digest(dict(contract))
    assert first == second
    changed = {
        **contract,
        "duration": {
            **contract["duration"],
            "minimum_final_duration_seconds": 1260,
        },
    }
    assert mission_product_contract_digest(changed) != first


def test_planner_projection_is_bounded_and_lossless():
    contract = materialize_br_no_gta_mission_product_contract()
    assert bounded_planner_product_contract_projection(contract) == contract


def test_historical_8_12_min_proposal_is_rejected():
    contract = materialize_br_no_gta_mission_product_contract()
    validation = validate_mission_plan_product_contract(
        _proposal_with_duration("duration 8-12 min"),
        contract,
    )
    assert validation["valid"] is False
    assert any(
        item.startswith("PRODUCT_DURATION_CONTRACT_VIOLATION:")
        for item in validation["violations"]
    )


def test_20_25_min_proposal_is_accepted():
    contract = materialize_br_no_gta_mission_product_contract()
    validation = validate_mission_plan_product_contract(
        _proposal_with_duration("duration 20-25 min; no artificial padding"),
        contract,
    )
    assert validation["valid"] is True
    assert validation["violations"] == []


def test_semantic_planner_prompt_receives_duration_and_padding_contract():
    contract = materialize_br_no_gta_mission_product_contract()
    prompt = build_semantic_planner_prompt(_planner_context(contract))
    assert "product_contract" in prompt
    assert "minimum_final_duration_seconds" in prompt
    assert "1200" in prompt
    assert "1500" in prompt
    assert "artificial_padding_forbidden" in prompt


def test_post_proposal_validation_rejects_historical_duration_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
):
    contract = materialize_br_no_gta_mission_product_contract()
    proposal = _proposal_with_duration("duration 8-12 min")
    result = SemanticPlannerResult(
        proposal=proposal,
        provider_evidence={"provider": "historical-replay"},
        prompt_sha256="0" * 64,
        provider_call_count=1,
    )

    monkeypatch.setattr(
        "app.services.harness_adaptive_planning_service."
        "propose_semantic_mission_plan",
        lambda *args, **kwargs: result,
    )
    with pytest.raises(
        RuntimeError,
        match="PRODUCT_DURATION_CONTRACT_VIOLATION",
    ):
        propose_validated_semantic_plan(
            _planner_context(contract),
            inference=lambda *_args, **_kwargs: {},
            max_replans=0,
        )


def test_adaptive_context_checks_declared_product_contract_digest(monkeypatch):
    contract = materialize_br_no_gta_mission_product_contract()
    goal = {
        "human_goal": "Produce BR no GTA 6 content",
        "project": "BR-no-GTA",
        "subject": "production",
        "goal_id": "goal-product-contract-digest",
        "mission_class": "GTA6_INTELLIGENCE",
        "canonical_state": {
            "mission_product_contract": contract,
            "product_contract_digest": "sha256:" + "0" * 64,
        },
        "conversation_state": {},
    }
    monkeypatch.setattr(
        "app.services.harness_adaptive_planning_service."
        "learning_repository.list_memories",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.harness_adaptive_planning_service."
        "learning_repository.list_episodes",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.harness_adaptive_planning_service."
        "learning_repository.list_canonical_human_decisions",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.harness_adaptive_planning_service."
        "learning_repository.list_competence",
        lambda **_kwargs: [],
    )
    with pytest.raises(ValueError, match="MISSION_PRODUCT_CONTRACT_DIGEST_MISMATCH"):
        build_semantic_planning_context(
            goal=goal,
            bounded_memory_context={},
            resource_bounds={"max_tasks_per_mission": 8},
            provider_health={},
        )
