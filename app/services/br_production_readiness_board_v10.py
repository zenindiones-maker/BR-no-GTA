"""Deterministic production blocker diagnosis, separate from render and voice approval.

A hash-consistent QA receipt is NOT a trusted signature and cannot authorize
production, learning, publication or TTS identity. Recommend the next bounded
experiment; do not rerun or mutate media here.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.services.br_production_forensic_qa_v10 import SCHEMA as QA_SCHEMA

BOARD_SCHEMA="BRProductionStartReadinessBoard/v1"
SHA=re.compile(r"^[a-f0-9]{64}$")

REMEDIATION={
    "EXPECTED_ONE_VIDEO_STREAM":"INSPECT_VIDEO_MUX_AND_RENDER_WORKER",
    "EXPECTED_ONE_AUDIO_STREAM":"REBUILD_PRIVATE_APPROVED_AUDIO_MUX",
    "UNKNOWN_OR_INVALID_DURATION":"INSPECT_FINALIZE_AND_CONTAINER_INTEGRITY",
    "VIDEO_DURATION_NOT_20_TO_25_MINUTES":"REPLAN_ORIGINAL_EDITORIAL_CONTENT_NO_PADDING",
    "CANARY_DURATION_OUTSIDE_BOUNDS":"REENCODE_BOUNDED_CANARY",
    "VIDEO_DIMENSIONS_INCORRECT":"FIX_RENDER_RESOLUTION_AND_PROFILE",
    "VIDEO_CODEC_NOT_H264":"FIX_VIDEO_CODEC_PROFILE",
    "VIDEO_PIXEL_FORMAT_NOT_YUV420P":"FIX_VIDEO_PIXEL_FORMAT",
    "VIDEO_AVERAGE_FPS_NOT_30":"FIX_FRAME_TIMESTAMP_AND_OUTPUT_FPS",
    "VIDEO_NOMINAL_FPS_NOT_30":"FIX_FRAME_TIMESTAMP_AND_OUTPUT_FPS",
    "AUDIO_CODEC_NOT_AAC":"FIX_AUDIO_ENCODER",
    "AUDIO_CHANNELS_NOT_STEREO":"REVIEW_APPROVED_STEREO_OUTPUT",
    "AUDIO_SAMPLE_RATE_NOT_48KHZ":"FIX_AUDIO_SAMPLE_RATE",
    "SAMPLED_MEDIA_DECODE_FAILED":"ISOLATE_CORRUPT_SEGMENT_AND_REENCODE",
    "AUDIO_VOLUME_MEASUREMENT_FAILED":"REVIEW_DECODE_AND_FFMPEG_FILTER",
    "SAMPLED_AUDIO_SILENT_OR_TOO_LOW":"INVESTIGATE_AUDIO_MIX_OR_MISSING_NARRATION",
    "ALL_SAMPLED_AUDIO_SILENT_OR_TOO_LOW":"INVESTIGATE_AUDIO_MIX_OR_MISSING_NARRATION",
    "VISUAL_HEURISTIC_FILTER_FAILED":"REVIEW_FFMPEG_VISUAL_DETECTORS",
}


def _digest(content:dict) -> str:
    return hashlib.sha256(json.dumps(
        content,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()


def diagnose_technical_readiness(receipt:dict[str,Any]) -> dict[str,Any]:
    if (not isinstance(receipt,dict) or receipt.get("schema_version")!=QA_SCHEMA
        or not isinstance(receipt.get("receipt_sha256"),str)
        or not SHA.fullmatch(receipt["receipt_sha256"])
        or receipt["receipt_sha256"]!=_digest({
            k:v for k,v in receipt.items() if k!="receipt_sha256"
        })):
        raise ValueError("PRODUCTION_QA_RECEIPT_UNVERIFIED_OR_TAMPERED")
    if (receipt.get("publish_authorized") is not False
        or receipt.get("voice_identity_verified") is not False
        or receipt.get("human_review_approved") is not False
        or receipt.get("harness_learning_write")!="NOT_ATTEMPTED"):
        raise ValueError("PRODUCTION_QA_RECEIPT_ESCAPED_AUTHORITY")
    failures=receipt.get("failure_codes")
    if (not isinstance(failures,list) or any(not isinstance(x,str) or x not in REMEDIATION for x in failures)
        or len(set(failures))!=len(failures)):
        raise ValueError("PRODUCTION_QA_UNKNOWN_FAILURE_CODES")
    expected="TECHNICAL_QA_FAIL" if failures else "TECHNICAL_SAMPLED_QA_PASS"
    if receipt.get("status")!=expected:
        raise ValueError("PRODUCTION_QA_RECEIPT_STATUS_INCONSISTENT")
    tasks=sorted(set(REMEDIATION[x] for x in failures))
    if not failures:
        tasks=["COMPLETE_FULL_DURATION_DECODE_AND_CREATIVE_HUMAN_REVIEW"]
    if receipt.get("profile")!="br_no_gta_1080p_master":
        tasks.append("VALIDATE_REAL_20_TO_25_MIN_1080P_MASTER")
    tasks.extend([
        "VERIFY_BR_OWNER_V1_APPROVED_VOICE_WITH_PRIVATE_HUMAN_REVIEW",
        "VERIFY_CLAIMS_SOURCE_LICENSES_EDITORIAL_AND_BRANDING",
        "VERIFY_TELEGRAM_AUDITION_AND_FINAL_HUMAN_APPROVAL",
    ])
    result={
        "schema_version":BOARD_SCHEMA,
        "status":"PRODUCTION_RELEASE_BLOCKED",
        "technical_status":expected,
        "technical_canary_only":receipt.get("profile")=="synthetic_ci_canary",
        "technical_receipt_sha256":receipt["receipt_sha256"],
        "source_sha256":receipt.get("source_sha256"),
        "blocked_reasons":sorted(set(failures)),
        "ordered_work_items":list(dict.fromkeys(tasks)),
        "task_execution_attempted":False,
        "can_start_offline_original_content_research":True,
        "can_start_media_qa_experiments":True,
        "can_start_publication":False,
        "owner_voice_approval_verified":False,
        "narration_delivery_to_telegram_verified":False,
        "editorial_and_asset_rights_verified":False,
        "full_episode_decode_verified":False,
        "release_approved_by_human":False,
        "no_automatic_production_resume":True,
        "no_automatic_tool_promotion":True,
        "evidence_trust_boundary":"QA digest checks consistency, not origin authenticity or independent reviewer identity",
    }
    result["board_sha256"]=_digest(result)
    return result
