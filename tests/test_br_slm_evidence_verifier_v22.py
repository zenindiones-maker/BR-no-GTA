from __future__ import annotations

from hashlib import sha256
import json
import pytest

from app.services.br_slm_evidence_verifier_v22 import verify_shadow

GOLD = [("visual", "Observe frames of an owned video"), ("ledger", "Read private delivery receipts"), ("abstain", "Write a poem")]
MODEL = "sentence-transformers/paraphrase-MiniLM-L3-v2"
REVISION = "4056ec5a34457110fd02a60216d646e012dbd988"
SHA = "84007b609c7a626b0adf825b1e36b839e705cd5995b4865b6e6696541d0a6350"


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def receipt():
    rows = []
    for label, text in GOLD:
        rows.append(dict(label=label, text_sha256=sha256(text.encode()).hexdigest(),
                         predicted=label, correct=True, model_executed=True,
                         latency_ms=10.0, tool_invoked=False, can_authorize=False, paid_calls=0))
    result = dict(schema_version="BRShadowSLMDecisionBenchmark/v21", model=MODEL,
                  revision=REVISION, onnx_sha256=SHA, actual_onnx_cpu_inference=True,
                  executable_authority="NONE_SHADOW_ONLY", published=False,
                  voice_training_authorized=False, ready_to_replace_v19_router=False,
                  operational_model_professional=False, real_tool_use_verified=False,
                  paid_calls=0, results=rows, case_count=3, in_domain_count=2,
                  out_of_distribution_count=1, in_domain_accuracy=1.0,
                  ood_abstention_accuracy=1.0, frozen_domain_threshold=0.85,
                  frozen_ood_threshold=1.0, status="SHADOW_SMALL_MODEL_INITIAL_CHECK_PASS",
                  p50_latency_ms=10.0, max_latency_ms=10.0)
    result["receipt_sha256"] = digest(result)
    return result


def verify(x, gold=GOLD):
    return verify_shadow(x, gold_cases=gold, expected_model=MODEL,
                         expected_revision=REVISION, expected_onnx_sha256=SHA,
                         expected_case_count=len(gold))


def resign(r):
    r["receipt_sha256"] = digest({k: v for k, v in r.items() if k != "receipt_sha256"})
    return r


def test_consistent_receipt_never_authorizes_promotion():
    r = verify(receipt())
    assert r["domain_correct"] == 2
    assert r["ood_correct"] == 1
    assert r["promotion_authorized"] is False
    assert r["professional_specialist_verified"] is False
    assert r["integrity"] == "VERIFIED_STRUCTURAL_CONSISTENCY_NOT_PROVEN_AUTHENTICITY"


def test_recomputed_hash_does_not_hide_wrong_correct_flag():
    r = receipt()
    r["results"][1]["predicted"] = "visual"
    with pytest.raises(ValueError, match="V22_ROW_CORRECT_FLAG"):
        verify(resign(r))


def test_modified_gold_hash_is_rejected_even_if_resigned():
    r = receipt()
    r["results"][1]["text_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="V22_FROZEN_CASE_IDENTITY"):
        verify(resign(r))


def test_unpermitted_tool_side_effect_is_denied():
    r = receipt()
    r["results"][0]["can_authorize"] = True
    with pytest.raises(ValueError, match="V22_SECURITY_BOUNDARY_ROW"):
        verify(resign(r))


def test_missing_digest_and_model_mismatch_fail_closed():
    r = receipt()
    r["receipt_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="V22_RECEIPT_INCONSISTENT"):
        verify(r)
    with pytest.raises(ValueError, match="V22_MODEL_PROVENANCE_MISMATCH"):
        verify_shadow(receipt(), gold_cases=GOLD, expected_model="other",
                      expected_revision=REVISION, expected_onnx_sha256=SHA,
                      expected_case_count=3)


def test_missing_model_execution_for_domain_rejected():
    r = receipt()
    r["results"][0]["model_executed"] = False
    with pytest.raises(ValueError, match="V22_DOMAIN_WITHOUT_MODEL"):
        verify(resign(r))


def test_prevented_ood_is_not_counted_as_model_decision():
    r = receipt()
    r["results"][2]["model_executed"] = False
    reviewed = verify(resign(r))
    assert reviewed["model_only_ood_trials"] == 0
    assert reviewed["policy_preempted_ood"] == 1


def test_changed_aggregate_and_changed_threshold_both_rejected():
    r = receipt()
    r["in_domain_accuracy"] = 0.7
    with pytest.raises(ValueError, match="V22_AGGREGATE_MISMATCH"):
        verify(resign(r))
    r = receipt()
    r["frozen_domain_threshold"] = 0.5
    with pytest.raises(ValueError, match="V22_THRESHOLD_CHANGED"):
        verify(resign(r))


def test_rejected_model_errors_are_diagnosed_not_promoted():
    r = receipt()
    r["results"][1]["predicted"] = "abstain"
    r["results"][1]["correct"] = False
    r["in_domain_accuracy"] = 0.5
    r["status"] = "SHADOW_SMALL_MODEL_QUALITY_NOT_SUFFICIENT"
    review = verify(resign(r))
    assert review["model_quality"] == "REJECTED"
    assert len(review["mismatches"]) == 1
    assert review["mismatches"][0]["expected"] == "ledger"
    assert review["promotion_authorized"] is False


def test_new_holdout_is_frozen_distinct_and_bounded():
    import ast
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts/br_slm_heldout_probe_v22.py"
    tree = ast.parse(path.read_text())
    holdout = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign)
                                  and any(isinstance(t, ast.Name) and t.id == "HOLDOUT" for t in node.targets)))
    assert len(holdout) == 28
    assert len(set(holdout)) == 28
    assert sum(label == "visual" for label, _ in holdout) == 8
    assert sum(label == "ledger" for label, _ in holdout) == 8
    assert sum(label == "abstain" for label, _ in holdout) == 12
    assert all(0 < len(text) <= 320 for _, text in holdout)
