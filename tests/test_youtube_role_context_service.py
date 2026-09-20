import json
from app.services.youtube_role_context_service import (
    MAX_SEMANTIC_CONTEXT_CHARS,
    ROLE_TARGET_PACKET_CHARS,
    build_production_packet,
    build_script_review_packet,
    build_seo_packet,
    build_thumbnail_packet,
)


def _claims():
    return [
        {
            "claim_id": "claim-1",
            "statement": "Rockstar lists GTA VI as coming November 19, 2026.",
            "verification_status": "VERIFIED",
            "source_hierarchy": "OFFICIAL_PRIMARY",
            "fact_check_result": "SUPPORTED",
            "fact_check_confidence": 1.0,
            "evidence_refs": ["https://www.rockstargames.com/VI"],
        }
    ]


def _plan():
    return {
        "content_item_id": 7,
        "script_id": 8,
        "idea_id": 9,
        "estimated_duration_seconds": 900.0,
        "hook": "Hook factual.",
        "editorial_evidence_refs": ["claim:claim-1"],
        "audio_requirements": [{"type": "voiceover", "language": "pt-BR"}],
        "visual_requirements": ["Use evidence-grounded visuals."],
        "scenes": [
            {
                "order": index,
                "narrative_block": f"Block {index}",
                "duration_seconds": 30.0,
                "visual_type": "gameplay",
                "visual_description": f"Concrete visual {index}",
                "narration": ("Narration grounded in evidence. " * 20),
                "requirements": ["evidence", "timing"],
                "segment_id": None,
            }
            for index in range(1, 31)
        ],
    }


def test_production_packet_preserves_lineage_and_full_artifact_hashes_under_budget():
    script = "HOOK\n" + ("Verified script paragraph. " * 500)
    plan = _plan()
    result = build_production_packet(
        goal_id="goal-1",
        content_item_id=7,
        script_id=8,
        production_plan_id=10,
        script_text=script,
        production_plan=plan,
        claims=_claims(),
        strategy_output={"audience": "BR", "angle": "verified", "promise": "facts"},
        full_context_chars=39_000,
    )
    packet = result["context"]
    metrics = result["metrics"]
    assert metrics["packet_chars"] < MAX_SEMANTIC_CONTEXT_CHARS
    assert metrics["packet_chars"] <= ROLE_TARGET_PACKET_CHARS["production-management"]
    assert metrics["packet_chars"] < metrics["full_context_chars"]
    assert metrics["chars_saved"] > 0
    assert packet["artifact_refs"]["script"] == "db:scripts:8"
    assert packet["artifact_refs"]["production_plan"] == "db:production_plans:10"
    assert len(packet["content_hashes"]["script_sha256"]) == 64
    assert len(packet["content_hashes"]["production_plan_sha256"]) == 64
    assert packet["provenance"]["goal_id"] == "goal-1"
    assert len(packet["scenes"]) == 30
    assert packet["editorial_summary"]["verified_facts"][0]["verification_status"] == "VERIFIED"


def test_seo_packet_uses_dense_summary_without_losing_artifact_reconstruction_refs():
    script = "HOOK\nPromise.\n\nCHAPTER ONE\n" + ("Fact based body. " * 300)
    result = build_seo_packet(
        goal_id="goal-1",
        content_item_id=7,
        script_id=8,
        production_plan_id=10,
        title="GTA VI factual update",
        script_text=script,
        production_plan=_plan(),
        claims=_claims(),
        strategy_output={"audience": "BR", "promise": "facts"},
        full_context_chars=18_000,
    )
    packet = result["context"]
    assert result["metrics"]["packet_chars"] < MAX_SEMANTIC_CONTEXT_CHARS
    assert packet["chapter_summaries"]
    assert packet["content_hashes"]["script_sha256"]
    assert packet["artifact_refs"]["script"] == "db:scripts:8"


def test_all_role_packet_builders_share_lineage_without_signature_failure():
    script = "HOOK\nPromise.\n\nCHAPTER ONE\n" + ("Fact based body. " * 120)
    common = dict(
        goal_id="goal-1",
        content_item_id=7,
        script_id=8,
        production_plan_id=10,
        script_text=script,
        production_plan=_plan(),
        claims=_claims(),
        strategy_output={"audience": "BR", "angle": "verified", "promise": "facts"},
        full_context_chars=30_000,
    )
    script_review = build_script_review_packet(**common)
    production = build_production_packet(**common)
    seo = build_seo_packet(title="GTA VI factual update", **common)
    thumbnail = build_thumbnail_packet(
        title="GTA VI factual update",
        seo_output={"search_intent": "gta vi", "keywords": ["gta vi"], "rationale": "verified"},
        **common,
    )
    for packet in (script_review, production, seo, thumbnail):
        assert packet["metrics"]["packet_chars"] < MAX_SEMANTIC_CONTEXT_CHARS
        assert packet["context"]["provenance"]["goal_id"] == "goal-1"
        assert packet["context"]["artifact_refs"]["script"] == "db:scripts:8"


def test_production_packet_survives_verbose_realistic_scene_plan_under_12k():
    script = "HOOK\n" + ("Verified factual paragraph with Jason Lucia Vice City. " * 900)
    plan = _plan()
    plan["scenes"] = [
        {
            **scene,
            "visual_description": ("Verbose visual direction with repeated narration context and evidence. " * 12),
            "media_search_terms": [("Rockstar GTA VI official scene search phrase " * 8)],
            "evidence_refs": [f"claim:{n}" for n in range(12)],
            "source_url": None,
            "asset_ref": None,
        }
        for scene in plan["scenes"]
    ]
    claims = [
        {
            **_claims()[0],
            "claim_id": f"claim-{index}",
            "statement": ("Long verified statement " * 40),
            "evidence_refs": [f"https://www.rockstargames.com/VI#{n}" for n in range(12)],
        }
        for index in range(8)
    ]
    result = build_production_packet(
        goal_id="goal-1",
        content_item_id=7,
        script_id=8,
        production_plan_id=10,
        script_text=script,
        production_plan=plan,
        claims=claims,
        strategy_output={
            "angle": "A" * 3000,
            "promise": "P" * 3000,
            "differentiation": "D" * 3000,
            "title_direction": "T" * 3000,
        },
        full_context_chars=80_000,
    )
    assert result["metrics"]["packet_chars"] <= 12_000
    assert result["metrics"]["target_packet_chars"] == 12_000
    packet = result["context"]
    assert "narration" not in json.dumps(packet["scenes"], ensure_ascii=False)
    assert "visual_description" not in json.dumps(packet["scenes"], ensure_ascii=False)
    assert packet["artifact_refs"]["production_plan"] == "db:production_plans:10"
