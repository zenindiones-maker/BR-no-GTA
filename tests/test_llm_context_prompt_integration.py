from pathlib import Path

from app.services.script_generator_service import _build_ai_prompt
from app.services.semantic_mission_planner_service import (
    build_semantic_planner_prompt,
)


def test_semantic_planner_routes_context_through_projection_boundary():
    prompt = build_semantic_planner_prompt({
        "human_goal": "Diagnose a bounded system incident.",
        "mission_class": "SYSTEM_IMPROVEMENT",
        "resource_bounds": {"max_tasks_per_mission": 4},
        "canonical_state": {"status": "RUNNING"},
        "competence_evidence": [{
            "capability_id": "cap-a",
            "tested_cases": 4,
            "success_rate": 1.0,
        }],
    })
    assert "CONTEXT_FORMAT=JSON_COMPACT" in prompt
    assert "UNTRUSTED_SUBORDINATE_DATA_BEGIN" in prompt
    assert "MissionPlan proposal only" in prompt


def test_editorial_prompt_routes_only_data_through_projection_boundary():
    prompt = _build_ai_prompt(
        title="Pauta",
        description="Descrição",
        research_context=None,
        editorial_context={
            "verified_claims": [{
                "claim_id": "claim-a",
                "statement": "Fato verificado.",
                "source": "https://www.rockstargames.com/VI",
                "evidence_refs": ["artifact:claim-a"],
            }],
        },
        target_duration_seconds=1200.0,
    )
    assert "CONTEXT_FORMAT=JSON_COMPACT" in prompt
    assert "UNTRUSTED_SUBORDINATE_DATA_BEGIN" in prompt
    assert "artifact:claim-a" in prompt
    assert "FORMATO OBRIGATÓRIO" in prompt


def test_research_semantic_context_is_bounded_before_serialization():
    source = Path(
        "app/services/production_mission_capability_adapters.py"
    ).read_text(encoding="utf-8")
    assert "context_text[:22000]" not in source
    assert "bound_llm_records(" in source
    assert 'route="research_semantic_synthesis"' in source
    assert "render_serialized_llm_context" in source
