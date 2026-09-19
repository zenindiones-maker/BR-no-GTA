from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from types import SimpleNamespace

from app.database.schema import initialize_schema
from app.services.fake_ai_provider import FakeAIProvider
from app.services.e2e_stage_checkpoint_service import (
    StageSpec,
    evaluate_reuse,
    invalidate_stage_and_descendants,
    record_completed_stage,
)
from app.services.script_generator_service import _generate_ai_structure
from app.services.script_spec_service import _build_narrative_blocks
from app.services.production_plan_service import create_production_plan
from app.services.youtube_department_service import (
    _semantic_output_contract,
    execute_youtube_specialist_capability,
    youtube_department_records,
)
from app.services.youtube_role_context_service import (
    build_production_packet,
    build_script_review_packet,
    build_seo_packet,
    build_thumbnail_packet,
)


PRODUCT_SPECIALISTS = (
    "youtube.department.content-strategy",
    "youtube.department.script-review",
    "youtube.department.seo",
    "youtube.department.production-management",
    "youtube.department.thumbnail-strategy",
)


def _script_contract() -> None:
    payload = (
        '{"hook":"HOOK","introduction":"INTRO","development":['
        '{"heading":"A","body":"B"},{"heading":"C","body":"D"},'
        '{"heading":"E","body":"F"}],"conclusion":"CONCLUSION","cta":"CTA"}'
    )
    provider = FakeAIProvider(response="```json\n" + payload + "\n```")
    structure = _generate_ai_structure(
        title="GTA VI",
        description="Descrição factual.",
        research_context=None,
        ai_provider=provider,
        editorial_context={"authority": "DEEPSEEK_HARNESS"},
        target_duration_seconds=900.0,
    )
    assert structure["hook"] == "HOOK"
    assert len(structure["development"]) == 3


def _specialist_contracts() -> None:
    records = {record.capability_id: record for record in youtube_department_records()}
    for capability_id in PRODUCT_SPECIALISTS:
        record = records[capability_id]
        result = execute_youtube_specialist_capability(
            record,
            {
                "objective": f"deterministic contract check for {capability_id}",
                "evidence_refs": ["claim:gate"],
                "constraints": ["no publication authority"],
            },
        )
        assert result["status"] == "EXECUTED"
        assert result["capability_id"] == capability_id
        assert result["authority"] == "DEEPSEEK_HARNESS"
        contract = _semantic_output_contract(capability_id)
        if contract is not None:
            parsed = json.loads(contract)
            assert isinstance(parsed, dict) and parsed


def _context_packet_contracts() -> None:
    plan = {
        "estimated_duration_seconds": 60.0,
        "hook": "h",
        "scenes": [
            {
                "order": 1,
                "narrative_block": "A",
                "duration_seconds": 30.0,
                "visual_type": "gameplay",
                "visual_description": "Specific visual A",
                "narration": "n",
            },
            {
                "order": 2,
                "narrative_block": "B",
                "duration_seconds": 30.0,
                "visual_type": "gameplay",
                "visual_description": "Specific visual B",
                "narration": "n",
            },
        ],
    }
    common = dict(
        goal_id="gate-goal",
        content_item_id=1,
        script_id=1,
        production_plan_id=1,
        script_text="HOOK\nh\n\nA\nbody",
        production_plan=plan,
        claims=[],
        strategy_output={"audience": "BR", "promise": "facts"},
        full_context_chars=30_000,
    )
    results = (
        build_script_review_packet(**common),
        build_production_packet(**common),
        build_seo_packet(title="GTA VI", **common),
        build_thumbnail_packet(
            title="GTA VI",
            seo_output={"search_intent": "gta vi"},
            **common,
        ),
    )
    for result in results:
        assert result["metrics"]["packet_chars"] < 24_000
        json.loads(json.dumps(result, ensure_ascii=False))



def _checkpoint_resume_contract() -> None:
    initialize_schema()
    spec = StageSpec(
        stage_id="research",
        input_payload={"query": "checkpoint contract gate", "source_url": "https://example.invalid"},
        code_paths=("scripts/local_deterministic_integration_gate.py",),
        provider_profile_version="deterministic-gate:v1",
        freshness_policy={"reusable": True},
    )
    goal_id = "local-deterministic-checkpoint-gate"
    checkpoint = record_completed_stage(
        goal_id=goal_id,
        spec=spec,
        output_payload={"status": "PASS", "value": 1},
        duration_ms=1234.5,
        provenance={"gate": "LOCAL_DETERMINISTIC_INTEGRATION"},
        source_run_id="local-gate",
        source_execution_id="local-gate",
    )
    assert checkpoint["stage_id"] == "research"
    reuse = evaluate_reuse(goal_id=goal_id, spec=spec)
    assert reuse["reusable"] is True, reuse
    assert float(reuse["checkpoint"]["duration_ms"]) == 1234.5
    invalidated = invalidate_stage_and_descendants(
        goal_id=goal_id,
        stage_id="research",
        reason="contract-gate-invalidation",
    )
    assert invalidated >= 1
    after = evaluate_reuse(goal_id=goal_id, spec=spec)
    assert after["reusable"] is False
    assert after["reason"] == "MISSING_CHECKPOINT"


def _production_plan_structure_contract() -> None:
    content = (
        "INTRODUÇÃO\nAbrimos com contexto factual sobre a Rockstar.\n\n"
        "BLOCO DINÂMICO SOBRE O ÁLBUM\nA Rockstar anunciou 34 faixas originais e energia de Vice City e Leonida.\n\n"
        "OUTRO HEADING ESPECÍFICO\nEste bloco separa fato verificado de interpretação editorial.\n\n"
        "CONCLUSÃO\nFechamos recapitulando os fatos verificados."
    )
    blocks = _build_narrative_blocks(content)
    headings = [item["heading"] for item in blocks]
    assert any("Bloco Dinâmico" in item for item in headings), headings
    assert any("Outro Heading" in item for item in headings), headings
    plan = create_production_plan({
        "id": 1,
        "script_id": 1,
        "idea_id": 1,
        "title": "GTA VI",
        "description": "d",
        "objective": "o",
        "audience": "pt-BR",
        "format": "YouTube editorial",
        "tone": "factual",
        "hook": "h",
        "cta": "c",
        "facts_sources": [],
        "verified_claims": [{
            "claim_id": "c1",
            "statement": "A Rockstar anunciou 34 faixas originais para GTA VI.",
        }],
        "youtube_strategy": {"angle": "official facts"},
        "editorial_evidence_refs": ["claim:c1"],
        "estimated_duration_seconds": 120.0,
        "narrative_blocks": blocks,
        "visual_requirements": [{"type": "context", "description": "official"}],
    })
    scenes = plan["scenes"]
    assert len(scenes) >= len(blocks)
    assert abs(sum(float(item["duration_seconds"]) for item in scenes) - 120.0) < 0.001
    assert all(float(item["duration_seconds"]) <= 30.001 for item in scenes)
    assert all(item.get("media_search_terms") for item in scenes)
    assert all("Visual relacionado diretamente ao tema" not in item["visual_description"] for item in scenes)
    assert sum(1 for item in scenes if item["visual_type"] == "title_card") <= 1

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()

    _script_contract()
    _specialist_contracts()
    _context_packet_contracts()
    _production_plan_structure_contract()
    _checkpoint_resume_contract()

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = {
        "status": "PASS",
        "LOCAL_DETERMINISTIC_INTEGRATION": "PASS",
        "specialists_checked": list(PRODUCT_SPECIALISTS),
        "PRODUCTION_PLAN_STRUCTURE_CONTRACT": "PASS",
        "CHECKPOINT_RESUME_CONTRACT": "PASS",
        "elapsed_ms": round(elapsed_ms, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("LOCAL_DETERMINISTIC_INTEGRATION=PASS")
    print("PRODUCTION_PLAN_STRUCTURE_CONTRACT=PASS")
    print("CHECKPOINT_RESUME_CONTRACT=PASS")
    print(f"LOCAL_DETERMINISTIC_INTEGRATION_MS={elapsed_ms:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
