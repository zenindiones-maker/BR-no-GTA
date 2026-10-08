"""Unprivileged, read-only production readiness preflight for BR-no-GTA.

Designed for independently collected operator evidence. Does NOT read a
Telegram token, load private voice material, call a TTS model, train a model,
resume a failed job, or grant permission to publish.

A SHA-256 of a local JSON report is a consistency digest, NOT a signature.
No unauthenticated field in the supplied report can authorize production.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "BRGroundedLaunchPreflight/v1"
_LEDGER_STATES = {"CONFIRMED", "PENDING", "FAILED", "NOT_STARTED", "SENDING", "BLOCKED"}
_GATES = {"PASS", "FAIL", "PENDING", "NOT_RUN", "UNKNOWN"}
_REVIEWS = {"APPROVED", "REJECTED", "PENDING", "NOT_RECORDED"}
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$")
_SHA = re.compile(r"^[a-f0-9]{40}$")
_LLAMA_SHA = "7af909522a951e3ad9f022ea6f88b6755257eaa5"


def _sha_json(doc: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        doc,sort_keys=True,ensure_ascii=False,allow_nan=False,
        separators=(",",":"),
    ).encode("utf-8")).hexdigest()


def inspect_ledger_head(ledger: Any) -> dict[str, Any]:
    """Parse only explicitly allowed nonsecret ledger fields.

    Never output the received pack ID, clone audio hash, review token,
    Telegram credentials, text, prompt, or owner reference paths.
    """
    if not isinstance(ledger,dict):
        raise ValueError("LAUNCH_LEDGER_JSON_OBJECT_REQUIRED")
    state=ledger.get("state")
    identity=ledger.get("clone_identity_gate")
    content=ledger.get("content_audio_prescreen")
    review=ledger.get("human_review")
    effect=ledger.get("side_effect_status")
    if (state not in _LEDGER_STATES
        or identity not in _GATES
        or content not in _GATES
        or review not in _REVIEWS
        or effect not in {"SENT","PENDING","NONE","NOT_STARTED","BLOCKED","AMBIGUOUS"}):
        raise ValueError("LAUNCH_LEDGER_FIELDS_NOT_RECOGNIZED")
    ids=ledger.get("confirmed_message_ids")
    if not isinstance(ids,dict):
        raise ValueError("LAUNCH_LEDGER_TELEGRAM_IDS_INVALID")
    three=("reference","clone","control")
    present=all(type(ids.get(k)) is int and ids[k]>0 for k in three)
    ordered=present and ids["reference"]<ids["clone"]<ids["control"]
    delivered=bool(state=="CONFIRMED" and effect=="SENT" and ordered)
    contradictory=bool(
        review=="APPROVED" and (identity!="PASS" or content!="PASS")
    )
    # Real provider send confirmation is externally authenticated, not merely a
    # local JSON saying CONFIRMED. "reported" is deliberately not "proved".
    return {
        "ledger_state_reported":state,
        "telegram_delivery_reported":delivered,
        "telegram_ids_order_valid":ordered,
        "last_reported_clone_message_id":ids.get("clone") if ordered else None,
        "identity_gate_reported":identity,
        "content_gate_reported":content,
        "human_review_reported":review,
        "inconsistent_reported_approval":contradictory,
        "telemetry_authenticated_in_this_preflight":False,
        "voice_runtime_activation_authorized":False,
        "voice_technical_approved_here":False,
    }


def inspect_llama_admission(policy: Any) -> dict[str, Any]:
    if not isinstance(policy,dict):
        raise ValueError("LAUNCH_LLAMA_POLICY_OBJECT_REQUIRED")
    from scripts.br_llamafactory_admission_v13 import admission_policy
    admission_policy(policy)
    return {
        "release":"v0.9.5",
        "source_commit":_LLAMA_SHA,
        "source_only_policy_recognized":True,
        "installed_on_current_workstation_verified":False,
        "cli_import_verified_here":False,
        "model_runtime_ready":False,
        "gpu_cost_admitted":False,
        "training_permitted":False,
        "tts_owner_voice_training_permitted":False,
    }


def build_grounded_launch_preflight(
    *,ledger_head: Any,llama_policy: Any,
    latest_attempt: dict[str,Any]|None=None,
    media_evidence: dict[str,Any]|None=None,
) -> dict[str, Any]:
    voice=inspect_ledger_head(ledger_head)
    llama=inspect_llama_admission(llama_policy)
    if latest_attempt is not None:
        if (not isinstance(latest_attempt,dict)
            or set(latest_attempt)!={"run_id","failure_class"}
            or type(latest_attempt["run_id"]) is not int
            or latest_attempt["run_id"]<=0
            or latest_attempt["failure_class"] not in {
                "LEDGER_FAST_FORWARD_PUSH_REJECTED",
                "RUNNER_SHUTDOWN",
                "NONE",
            }):
            raise ValueError("LAUNCH_LATEST_ATTEMPT_INVALID")
    if media_evidence is not None:
        if (not isinstance(media_evidence,dict)
            or media_evidence.get("schema_version")!="BRFullMediaDecodeEvidence/v1"
            or media_evidence.get("profile") not in {
                "synthetic_ci_canary","br_no_gta_1080p_master"
            }):
            raise ValueError("LAUNCH_MEDIA_EVIDENCE_SCHEMA_INVALID")
    blockers=[]
    next_steps=[]
    if voice["inconsistent_reported_approval"]:
        blockers.append("VOICE_APPROVAL_CONTRADICTS_FAILED_GATES")
        next_steps.append("INDEPENDENT_LEDGER_CONSISTENCY_REVIEW")
    if voice["identity_gate_reported"]!="PASS":
        blockers.append("OWNER_SPEAKER_IDENTITY_NOT_VERIFIED")
        next_steps.append("MEASURE_OWNER_MISMATCH_USING_CONSENTED_MATCHED_REFERENCES")
    if voice["content_gate_reported"]!="PASS":
        blockers.append("OWNER_PRONUNCIATION_OR_AUDIO_NOT_VERIFIED")
        next_steps.append("AUDIT_SEGMENT_ASR_AND_VAICY_SITI_WITH_HUMAN")
    if voice["human_review_reported"]!="APPROVED":
        blockers.append("HUMAN_OWNER_VOICE_APPROVAL_MISSING")
        next_steps.append("REQUEST_PRIVATE_OWNER_LISTENING_AFTER_QA")
    if not voice["telegram_delivery_reported"]:
        blockers.append("TELEGRAM_RECEIPT_NOT_CONFIRMED_IN_REPORTED_LEDGER")
        next_steps.append("READ_BACK_REMOTE_LEDGER_BEFORE_ANY_DELIVERY")
    if (latest_attempt and latest_attempt["failure_class"]==
        "LEDGER_FAST_FORWARD_PUSH_REJECTED"):
        blockers.append("LATEST_LEDGER_PUSH_FAILED_DESPITE_PRIOR_SEND")
        next_steps.append("READ_BACK_REMOTE_EXPECTED_SHA_AND_RECONCILE_NO_RESEND")
    # No live authenticated AV candidate inspected: even a self-consistent JSON
    # cannot independently attest a full episode's creative/rights QA.
    if media_evidence is None:
        blockers.append("NO_FULL_EPISODE_DECODE_EVIDENCE")
    elif media_evidence.get("profile")!="br_no_gta_1080p_master":
        blockers.append("CANARY_IS_NOT_20_MINUTE_MASTER")
    else:
        blockers.append("FULL_MASTER_AUTHENTICITY_AND_CREATIVE_REVIEW_NOT_VERIFIED")
    next_steps.append("RUN_ORIGINAL_20_TO_25_MINUTE_RENDER_AFTER_APPROVED_VOICE")
    blockers.extend((
        "ORIGINAL_ASSET_RIGHTS_AND_EDITORIAL_NOT_VERIFIED",
        "YOUTUBE_PRIVATE_HD_AND_FINAL_HUMAN_APPROVAL_NOT_VERIFIED",
        "AGENT_OFFICE_UPSTREAM_SECURITY_REVIEW_PENDING",
        "LLAMAFACTORY_TRAINING_RUNTIME_NOT_ADMITTED",
    ))
    next_steps.extend((
        "INDEPENDENT_EDITORIAL_ASSET_PROVENANCE_REVIEW",
        "VERIFY_AGENT_OFFICE_DEPENDENCIES_BEFORE_RUNNING_AGENT",
        "REQUIRE_SEPARATE_ZERO_COST_GPU_AND_MODEL_COMPATIBILITY_FOR_LLAMA",
        "AWAIT_EXPLICIT_OWNER_PRIVATE_RELEASE_APPROVAL",
    ))
    result={
        "schema_version":SCHEMA,
        "status":"PRODUCTION_RELEASE_BLOCKED",
        "ledger_head":voice,
        "llamafactory":llama,
        "latest_attempt_failure_class":latest_attempt["failure_class"] if latest_attempt else "NOT_PROVIDED",
        "media_evidence_type":"NOT_PROVIDED" if media_evidence is None else media_evidence["profile"],
        "blockers":sorted(set(blockers)),
        "next_bounded_experiments":list(dict.fromkeys(next_steps)),
        "new_audio_generated":False,
        "remote_git_mutation":False,
        "telegram_send_attempted":False,
        "trainer_started":False,
        "canonical_learning_changed":False,
        "release_authorization":"FORBIDDEN",
        "voice_identity_policy_changed":False,
        "review_provenance_verified":False,
        "data_trust":"OPERATOR_SUPPLIED_OFFLINE_EVIDENCE_NOT_CRYPTOGRAPHICALLY_ATTESTED",
    }
    result["receipt_sha256"]=_sha_json(result)
    return result
