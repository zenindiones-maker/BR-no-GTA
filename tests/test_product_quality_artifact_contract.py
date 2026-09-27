from __future__ import annotations

from pathlib import Path

from app.services.product_quality_artifact_contract import (
    PRODUCT_QUALITY_E2E_SCHEMA,
    assess_product_quality_artifact,
)


def _current_artifact() -> dict:
    return {
        "schema": PRODUCT_QUALITY_E2E_SCHEMA,
        "status": "PASS",
        "mission_id": "mission-a",
        "goal_id": "goal-a",
        "content_item_id": 1,
        "script_id": 2,
        "production_plan_id": 3,
        "youtube_entity_id": 4,
        "claims": [{"claim_id": "claim-a"}],
        "production_plan": {"scenes": [{"scene_id": "scene-a"}]},
        "youtube_package": {"status": "planned"},
        "structured_specialist_outputs": {
            "content_strategy": {},
            "script_review": {},
            "seo": {},
            "thumbnail": {},
            "production_management": {},
        },
        "metrics": {
            "verified_claims": 1,
            "script_word_count": 3200,
            "scene_count": 12,
            "max_scene_seconds": 28.0,
            "package_evidence_refs": 8,
            "target_duration_seconds": 1200.0,
            "generic_scene_ratio": 0.0,
            "title_card_ratio": 0.0,
            "media_resolvable_ratio": 1.0,
            "evidence_to_scene_coverage": 1.0,
        },
    }


def test_current_product_quality_artifact_is_compatible():
    result = assess_product_quality_artifact(_current_artifact())
    assert result["compatible"] is True
    assert result["reasons"] == []


def test_legacy_unversioned_product_artifact_is_not_reusable():
    artifact = _current_artifact()
    artifact.pop("schema")
    result = assess_product_quality_artifact(artifact)
    assert result["compatible"] is False
    assert "SCHEMA_VERSION_MISMATCH" in result["reasons"]


def test_missing_current_metric_invalidates_product_artifact():
    artifact = _current_artifact()
    artifact["metrics"].pop("generic_scene_ratio")
    result = assess_product_quality_artifact(artifact)
    assert result["compatible"] is False
    assert result["missing_metric_fields"] == ["generic_scene_ratio"]
    assert "REQUIRED_METRICS_MISSING" in result["reasons"]


def test_invalid_ratio_does_not_pass_compatibility_gate():
    artifact = _current_artifact()
    artifact["metrics"]["media_resolvable_ratio"] = 1.5
    result = assess_product_quality_artifact(artifact)
    assert result["compatible"] is False
    assert "media_resolvable_ratio" in result["invalid_metric_fields"]


def test_product_producer_emits_versioned_contract():
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "youtube_product_quality_e2e.py"
    ).read_text(encoding="utf-8")
    assert '"schema": PRODUCT_QUALITY_E2E_SCHEMA' in source


def test_resume_rejects_incompatible_product_without_fake_defaults():
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "restore_e2e_resume_state.py"
    ).read_text(encoding="utf-8")
    assert "assess_product_quality_artifact" in source
    assert "PRODUCT_ARTIFACT_CONTRACT_INCOMPATIBLE" in source
    assert '"reuse_product_package": (' in source
    assert '"RESUME_FROM_STAGE": "editorial-script"' in source
    assert "generic_scene_ratio" not in source
