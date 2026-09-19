from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from types import SimpleNamespace

from app.services.fake_ai_provider import FakeAIProvider
from app.services.script_generator_service import _generate_ai_structure
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()

    _script_contract()
    _specialist_contracts()
    _context_packet_contracts()

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = {
        "status": "PASS",
        "LOCAL_DETERMINISTIC_INTEGRATION": "PASS",
        "specialists_checked": list(PRODUCT_SPECIALISTS),
        "elapsed_ms": round(elapsed_ms, 3),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("LOCAL_DETERMINISTIC_INTEGRATION=PASS")
    print(f"LOCAL_DETERMINISTIC_INTEGRATION_MS={elapsed_ms:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
