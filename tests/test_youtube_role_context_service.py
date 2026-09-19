from app.services.youtube_role_context_service import (
    MAX_SEMANTIC_CONTEXT_CHARS,
    build_production_packet,
    build_seo_packet,
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
    assert metrics["packet_chars"] < metrics["full_context_chars"]
    assert metrics["chars_saved"] > 0
    assert packet["artifact_refs"]["script"] == "db:scripts:8"
    assert packet["artifact_refs"]["production_plan"] == "db:production_plans:10"
    assert len(packet["content_hashes"]["script_sha256"]) == 64
    assert len(packet["content_hashes"]["production_plan_sha256"]) == 64
    assert packet["provenance"]["goal_id"] == "goal-1"
    assert len(packet["scenes"]) == 30
    assert packet["verified_claims"][0]["verification_status"] == "VERIFIED"


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
