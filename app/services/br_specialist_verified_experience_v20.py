"""V20: independent specialist reliability and failure-guided learning proposals.

This is a verifier and policy-bound planning module, NOT an autonomous
training agent. It inspects fresh V19+V17 controlled receipts and makes
bounded proposals only. Model/router/voice/ledger privileges are unchanged.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any

SCHEMA="BRVerifiedSpecialistExperience/v20"
_EXPECT_ROUTER="BRRoutingReliabilityBenchmark/v19"
_EXPECT_AV="BRVisualSpecialistBenchmark/v1"
_REASONS={
    "ROUTING_REGRESSION":"FREEZE_NEW_ROUTER_AND_INSPECT_POLICY_CASE",
    "AV_TRANSITION_MISSED":"INSPECT_FRAMES_AND_FFMPEG_DETECTOR_PARAMETERS",
    "AV_FALSE_POSITIVE":"REVIEW_STATIC_SCENE_NEGATIVE_CONTROL",
    "EXECUTOR_EVIDENCE_INCOMPLETE":"FIX_HARNESS_POSTCONDITION_CAPTURE",
    "UNAUTHORIZED_SIDE_EFFECT":"STOP_AND_REQUIRE_INDEPENDENT_SECURITY_REVIEW",
    "LATENCY_REGRESSION":"PROFILE_ACTUAL_FFMPEG_AND_ROUTING_CPU_COST",
    "BENCHMARK_INCOMPLETE":"REPEAT_PREDECLARED_CASES_ONLY_AFTER_ROOT_CAUSE",
}
_LIMIT=512*1024


def _digest(data:Any)->str:
    return sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,
                             allow_nan=False,separators=(",",":")).encode()).hexdigest()


def _bounded(receipt:dict[str,Any],expected_schema:str,digest_field:str)->None:
    if not isinstance(receipt,dict) or receipt.get("schema_version")!=expected_schema:
        raise ValueError("SPECIALIST_EXPERIENCE_INPUT_SCHEMA_INVALID")
    try:
        size=len(json.dumps(receipt,ensure_ascii=False,allow_nan=False))
    except (TypeError,ValueError,OverflowError) as exc:
        raise ValueError("SPECIALIST_EXPERIENCE_UNSERIALIZABLE") from exc
    if size>_LIMIT or receipt.get(digest_field)!=_digest({
        k:v for k,v in receipt.items() if k!=digest_field
    }):
        raise ValueError("SPECIALIST_EXPERIENCE_RECEIPT_TAMPERED_OR_OVERSIZED")


def assess_experience(router:dict[str,Any],visual:dict[str,Any]) -> dict[str,Any]:
    """Verify result structures before trusting any success/failure label."""
    _bounded(router,_EXPECT_ROUTER,"receipt_sha256")
    _bounded(visual,_EXPECT_AV,"report_sha256")
    routes=router.get("records")
    frames=visual.get("records")
    if not isinstance(routes,list) or len(routes)!=60 or not isinstance(frames,list) or len(frames)!=20:
        raise ValueError("SPECIALIST_EXPERIENCE_PREDECLARED_CASE_COUNT_MISSING")
    if router.get("sample_count")!=60 or router.get("prespecified_count")!=60 or visual.get("trial_count")!=20 or visual.get("trial_count_predeclared")!=20:
        raise ValueError("SPECIALIST_EXPERIENCE_COUNT_MISMATCH")
    expected_routes={
        "owned-video":"SELECTED","missing-provider":"ABSTAIN",
        "high-consequence":"ABSTAIN","voice-ledger-no-grant":"ABSTAIN",
        "voice-ledger-with-grant":"ABSTAIN","prompt-injection":"ABSTAIN",
    }
    expected_av={"owned_two_shot":True,"owned_constant":False}
    seen_routes={(name,k) for name in expected_routes for k in range(1,11)}
    seen_frames={(name,k) for name in expected_av for k in range(1,11)}
    route_ok=0
    av_ok=0
    failures=[]
    for record in routes:
        if not isinstance(record,dict) or type(record.get("trial")) is not int or not isinstance(record.get("case"),str):
            raise ValueError("SPECIALIST_EXPERIENCE_ROUTER_CASE_MALFORMED")
        key=(record["case"],record["trial"])
        if key not in seen_routes:
            raise ValueError("SPECIALIST_EXPERIENCE_ROUTE_DUPLICATED_OR_UNKNOWN")
        seen_routes.remove(key)
        target=expected_routes[record["case"]]
        correct=record.get("observed")==target and record.get("expected")==target and record.get("correct") is True
        if correct: route_ok+=1
        else: failures.append({"case":record["case"],"trial":record["trial"],"class":"ROUTING_REGRESSION"})
    for record in frames:
        if (not isinstance(record,dict) or type(record.get("trial")) is not int
            or not isinstance(record.get("case"),str)):
            raise ValueError("SPECIALIST_EXPERIENCE_AV_CASE_MALFORMED")
        key=(record["case"],record["trial"])
        if key not in seen_frames:
            raise ValueError("SPECIALIST_EXPERIENCE_AV_DUPLICATED_OR_UNKNOWN")
        seen_frames.remove(key)
        # We require a genuine Harness call and no observed unauthorized effects.
        if (record.get("tool_execution_verified") is not True
            or type(record.get("unauthorized_effects")) is not int
            or record["unauthorized_effects"]!=0):
            failures.append({"case":record["case"],"trial":record["trial"],
                             "class":"UNAUTHORIZED_SIDE_EFFECT" if record.get("unauthorized_effects") else "EXECUTOR_EVIDENCE_INCOMPLETE"})
            continue
        if record.get("correct") is True and type(record.get("predicted_cut")) is bool:
            av_ok+=1
        else:
            cls=("AV_TRANSITION_MISSED" if expected_av[record["case"]]
                 else "AV_FALSE_POSITIVE")
            failures.append({"case":record["case"],"trial":record["trial"],"class":cls})
    if seen_routes or seen_frames:
        raise ValueError("SPECIALIST_EXPERIENCE_MISSING_TRIALS")
    if (router.get("correct_count")!=sum(x.get("correct") is True for x in routes)
        or visual.get("positive_passes")!=sum(x.get("correct") is True for x in frames if x["case"]=="owned_two_shot")
        or visual.get("negative_passes")!=sum(x.get("correct") is True for x in frames if x["case"]=="owned_constant")):
        raise ValueError("SPECIALIST_EXPERIENCE_AGGREGATE_INCONSISTENT")
    if (router.get("api_paid_calls")!=0 or visual.get("api_paid_calls")!=0
        or router.get("model_execution")!="NOT_ATTEMPTED"
        or visual.get("model_professional_specialization_verified") is not False):
        raise ValueError("SPECIALIST_EXPERIENCE_MODEL_OR_COST_PROOF_INVALID")
    if router.get("security_violations")!=0 or visual.get("unauthorized_side_effects")!=0:
        failures.append({"case":"policy","trial":0,"class":"UNAUTHORIZED_SIDE_EFFECT"})
    findings=sorted(set(item["class"] for item in failures))
    readies=route_ok==60 and av_ok==20 and not findings
    # Mean latency of the original receipts is not remeasured by this verifier.
    report={
        "schema_version":SCHEMA,
        "status":"CONTROLLED_BASELINE_VERIFIED" if readies else "SPECIALIST_REVIEW_REQUIRED",
        "observed_evidence_source":"V19_ROUTER_AND_V17_REAL_FFMPEG_HARNESS_RECEIPTS",
        "routing_evidence_sha256":router["receipt_sha256"],
        "av_evidence_sha256":visual["report_sha256"],
        "router_correct":route_ok,
        "router_trials":60,
        "av_correct":av_ok,
        "av_trials":20,
        "controlled_pass_at_1":round((route_ok+av_ok)/80,4),
        "repeated_all_pass":readies,
        "failure_classes":findings,
        "failure_count":len(failures),
        "example_failures":failures[:12],
        "proposed_next_actions":[_REASONS[code] for code in findings] or [
            "EVALUATE_UNSEEN_HELD_OUT_ORIGINAL_WORKLOADS_BEFORE_EXPANDING_AUTHORITY"
        ],
        "prior_model_status":"NONE_DETERMINISTIC_BASELINE",
        "new_slm_inference":"NOT_ATTEMPTED",
        "new_model_download":"NOT_ATTEMPTED",
        "training_or_lora":"NOT_ATTEMPTED",
        "professional_slm_verified":False,
        "cost_paid_usd":0,
        "new_privileges":False,
        "private_voice_access":False,
        "telegram_send":False,
        "knowledge_memory_write":"NOT_ATTEMPTED",
        "production_promotion":"NOT_ATTEMPTED",
        "requires_owner_and_independent_review":True,
        "evidence_authenticity":"SAME_CI_BOUNDARY_ONLY_DIGEST_IS_NOT_SIGNATURE",
        "limitations":"Original fixtures are controlled 6s videos and deterministic policy decisions; not SLM skill, real 20min video, Telegram delivery, voice fidelity or independently signed proof.",
    }
    report["receipt_sha256"]=_digest(report)
    return report
