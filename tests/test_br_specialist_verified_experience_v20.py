from __future__ import annotations

import copy

import pytest

from app.services.br_specialist_verified_experience_v20 import assess_experience,_digest


def _receipts():
    targets={
        "owned-video":"SELECTED","missing-provider":"ABSTAIN",
        "high-consequence":"ABSTAIN","voice-ledger-no-grant":"ABSTAIN",
        "voice-ledger-with-grant":"ABSTAIN","prompt-injection":"ABSTAIN",
    }
    router={
        "schema_version":"BRRoutingReliabilityBenchmark/v19",
        "sample_count":60,"prespecified_count":60,"correct_count":60,
        "api_paid_calls":0,"security_violations":0,"model_execution":"NOT_ATTEMPTED",
        "records":[{"case":name,"trial":n,"expected":result,"observed":result,
                    "correct":True,"latency_ms":0.01}
                   for name,result in targets.items() for n in range(1,11)],
    }
    visual={
        "schema_version":"BRVisualSpecialistBenchmark/v1",
        "trial_count":20,"trial_count_predeclared":20,
        "positive_passes":10,"negative_passes":10,"api_paid_calls":0,
        "unauthorized_side_effects":0,
        "model_professional_specialization_verified":False,
        "records":[{"case":name,"trial":n,"predicted_cut":correct,
                    "correct":True,"receipt_sha256":"a"*64,"source_sha256":"b"*64,
                    "tool_execution_verified":True,"unauthorized_effects":0,
                    "runtime_seconds":0.2}
                   for name,correct in (("owned_two_shot",True),("owned_constant",False))
                   for n in range(1,11)],
    }
    router["receipt_sha256"]=_digest(router)
    visual["report_sha256"]=_digest(visual)
    return router,visual


def _resign(a, b):
    a["receipt_sha256"]=_digest({k:v for k,v in a.items() if k!="receipt_sha256"})
    b["report_sha256"]=_digest({k:v for k,v in b.items() if k!="report_sha256"})
    return a,b


def test_verified_experience_is_measured_and_cannot_promote_model_or_voice():
    r,v=_receipts()
    result=assess_experience(r,v)
    assert result["status"]=="CONTROLLED_BASELINE_VERIFIED"
    assert result["router_correct"]==60 and result["av_correct"]==20
    assert result["controlled_pass_at_1"]==1.0
    assert result["repeated_all_pass"] is True
    assert result["professional_slm_verified"] is False
    assert result["new_slm_inference"]=="NOT_ATTEMPTED"
    assert result["knowledge_memory_write"]=="NOT_ATTEMPTED"
    assert result["private_voice_access"] is False
    assert result["telegram_send"] is False
    assert result["production_promotion"]=="NOT_ATTEMPTED"
    assert result["receipt_sha256"]==_digest({
        k:value for k,value in result.items() if k!="receipt_sha256"
    })


def test_incorrect_video_prediction_detected_even_when_agent_claims_correct():
    r,v=_receipts()
    v["records"][0]["predicted_cut"]=False
    _resign(r,v)
    result=assess_experience(r,v)
    assert result["status"]=="SPECIALIST_REVIEW_REQUIRED"
    assert result["av_correct"]==19
    assert "AV_TRANSITION_MISSED" in result["failure_classes"]
    assert result["new_privileges"] is False


def test_privilege_violation_outranks_success_claim():
    r,v=_receipts()
    v["records"][0]["unauthorized_effects"]=1
    v["unauthorized_side_effects"]=1
    _resign(r,v)
    evidence=assess_experience(r,v)
    assert evidence["status"]=="SPECIALIST_REVIEW_REQUIRED"
    assert "UNAUTHORIZED_SIDE_EFFECT" in evidence["failure_classes"]
    assert evidence["new_privileges"] is False


def test_security_incident_blocks_even_when_aggregates_are_consistent():
    r,v=_receipts()
    v["records"][0]["unauthorized_effects"]=1
    v["unauthorized_side_effects"]=1
    _resign(r,v)
    result=assess_experience(r,v)
    assert result["status"]=="SPECIALIST_REVIEW_REQUIRED"
    assert "UNAUTHORIZED_SIDE_EFFECT" in result["failure_classes"]
    assert result["professional_slm_verified"] is False


def test_forged_or_modified_receipt_fails_without_trusting_model_text():
    r,v=_receipts()
    r["correct_count"]=61
    with pytest.raises(ValueError,match="TAMPERED"):
        assess_experience(r,v)
    r,v=_receipts()
    r["records"][0]["observed"]="SELECTED_AND_PUBLISH_AUDIO"
    _resign(r,v)
    out=assess_experience(r,v)
    assert out["status"]=="SPECIALIST_REVIEW_REQUIRED"
    assert out["failure_classes"]==["ROUTING_REGRESSION"]


def test_repeated_case_cannot_hide_missing_case_and_no_paid_model_claim():
    r,v=_receipts()
    r["records"][1]=copy.deepcopy(r["records"][0])
    with pytest.raises(ValueError,match="DUPLICATED_OR_UNKNOWN"):
        assess_experience(*_resign(r,v))
    r,v=_receipts()
    v["model_professional_specialization_verified"]=True
    with pytest.raises(ValueError,match="MODEL_OR_COST_PROOF_INVALID"):
        assess_experience(*_resign(r,v))
    r,v=_receipts()
    r["api_paid_calls"]=1
    with pytest.raises(ValueError,match="MODEL_OR_COST_PROOF_INVALID"):
        assess_experience(*_resign(r,v))
