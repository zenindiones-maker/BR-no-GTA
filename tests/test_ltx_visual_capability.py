from app.services.ltx_visual_capability_service import (
    GENERATED_VISUAL, LTX_RUNTIME_UNAVAILABLE, build_generated_visual_asset,
    detect_ltx_runtime,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

def test_generated_visual_is_typed_non_evidence():
    asset = build_generated_visual_asset(
        mission_id="m1", task_id="t1", prompt="abstract editorial transition",
        source_asset_refs=("official:asset-1",), generation_parameters={"seed": 7},
    )
    assert asset.origin == GENERATED_VISUAL
    assert asset.generator == "LTX-2.5"
    assert asset.evidence_eligible is False
    assert asset.factual_status == "SYNTHETIC_EDITORIAL_VISUAL_ONLY"
    assert asset.prompt_provenance["evidence_source"] is False

def test_registry_keeps_ltx_subordinate_and_runtime_gated():
    record = GLOBAL_CAPABILITY_REGISTRY.get("visual.generate.transform.ltx-2.5")
    assert record is not None
    assert record.maturity == "PARTIAL"
    assert record.health_policy == "LTX_RUNTIME_ELIGIBILITY_REQUIRED"
    assert record.fallback_eligibility is False
    assert "vedit" in record.policy_tags
    assert "non-evidence" in record.policy_tags

def test_missing_runtime_is_normal_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("LTX_MODEL_ACCESS_ACCEPTED", raising=False)
    monkeypatch.delenv("LTX_MODEL_ROOT", raising=False)
    state = detect_ltx_runtime()
    assert state.status == LTX_RUNTIME_UNAVAILABLE
    assert state.cuda_available is False
    assert state.model_ready is False
