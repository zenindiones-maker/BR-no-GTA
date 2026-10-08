"""Persisted DeepSeek Harness-scoped access to pixel evidence.

No observed media or prompts can impersonate authorization or choose a
different executor. No generic agent may read a private audio identity file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.harness_authorization_service import validate_harness_authorization

CAPABILITY_ID="reverse-engineering.multimodal.sensory-pixels-v12"
_FORBIDDEN={"owner_voice","private_material","audition-ledger",".run",".git",".ssh",".env","credentials","tokens"}


def _admit(auth,raw:str,*,directory:bool=False)->Path:
    roots=auth.lineage.get("allowed_media_roots")
    if not isinstance(roots,list) or not 1<=len(roots)<=8:
        raise PermissionError("SENSORY_HARNESS_MEDIA_ROOTS_MISSING")
    supplied=Path(str(raw or ""))
    if not supplied.is_absolute() or supplied.is_symlink():
        raise PermissionError("SENSORY_HARNESS_ABSOLUTE_NONLINK_REQUIRED")
    target=supplied.resolve(strict=True)
    if target.is_dir()!=directory:
        raise PermissionError("SENSORY_HARNESS_SOURCE_TYPE_INVALID")
    if any(part.lower() in _FORBIDDEN for part in target.parts):
        raise PermissionError("SENSORY_HARNESS_PRIVATE_MEDIA_FORBIDDEN")
    granted=False
    for root_text in roots:
        original=Path(str(root_text))
        if not original.is_absolute() or original.is_symlink() or not original.is_dir():
            continue
        root=original.resolve(strict=True)
        if any(part.lower() in _FORBIDDEN for part in root.parts):
            continue
        if root in target.parents:
            granted=True
            break
    if not granted:
        raise PermissionError("SENSORY_HARNESS_SCOPE_DENIED")
    return target


def execute_authorized_pixel_observation(
    *,authorization:Any,routing_decision:Any,payload:dict[str,Any],
)->dict[str,Any]:
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    auth=validate_harness_authorization(
        authorization,expected_action="RESEARCH",expected_subject=f"capability:{CAPABILITY_ID}"
    )
    capability=GLOBAL_CAPABILITY_REGISTRY.get(CAPABILITY_ID)
    if capability is None or not capability.execution_enabled:
        raise PermissionError("SENSORY_CAPABILITY_NOT_REGISTERED")
    if (routing_decision.selected_capability_id!=CAPABILITY_ID
        or routing_decision.authorized_action!="RESEARCH"
        or routing_decision.selected_executor_binding!=capability.executor_binding):
        raise PermissionError("SENSORY_HARNESS_ROUTE_MISMATCH")
    required={"source_path","rights","kind","private_workspace"}
    if (not isinstance(payload,dict)
        or not required.issubset(payload)
        or not set(payload).issubset(required|{"scene_scan"})
        or type(payload.get("scene_scan",False)) is not bool
        or (payload.get("scene_scan",False) and payload["kind"]!="owner_video_mp4")
        or payload["rights"]!="owned"):
        raise PermissionError("SENSORY_HARNESS_PAYLOAD_DENIED")
    source=_admit(auth,payload["source_path"])
    workspace=_admit(auth,payload["private_workspace"],directory=True)
    if workspace in source.parents or source in workspace.parents:
        raise PermissionError("SENSORY_SOURCE_WORKSPACE_COLLISION")
    from app.services.br_harness_sensory_pixel_v12 import inspect_pixel_evidence
    report=inspect_pixel_evidence(source,kind=payload["kind"],private_workspace=workspace)
    timeline=None
    if payload.get("scene_scan",False):
        from app.services.br_harness_visual_timeline_v16 import observe_timeline
        timeline=observe_timeline(source=source,authoritative_pixel_evidence=report)
    return {
        "schema_version":"BRHarnessSensoryObservationExecution/v1",
        "status":"OBSERVED_PIXEL_EVIDENCE_ONLY",
        "capability_id":CAPABILITY_ID,
        "authorization_id":auth.authorization_id,
        "harness_decision_id":auth.harness_decision_id,
        "execution_id":auth.execution_id,
        "evidence":report,
        "visual_timeline_evidence":timeline,
        "agents_can_consume_private_frames":False,
        "scene_semantics_certified":False,
        "authority":"DEEPSEEK_HARNESS",
        "canonical_promotion":"NOT_ATTEMPTED",
        "production_mutation":False,
        "publication":"FORBIDDEN",
    }



PRODUCTION_QA_CAPABILITY_ID="production.technical-media-forensics"


def execute_authorized_production_media_qa(
    *, authorization:Any, routing_decision:Any, payload:dict[str,Any],
)->dict[str,Any]:
    """Unify V10/V10b original MP4 technical evidence under one Harness gate."""
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    from app.services.br_production_forensic_qa_v10 import analyze_render
    from app.services.br_full_media_decode_v10b import verify_full_decode

    auth=validate_harness_authorization(
        authorization,expected_action="RESEARCH",
        expected_subject=f"capability:{PRODUCTION_QA_CAPABILITY_ID}",
    )
    capability=GLOBAL_CAPABILITY_REGISTRY.get(PRODUCTION_QA_CAPABILITY_ID)
    if (capability is None or not capability.execution_enabled
        or routing_decision.selected_capability_id!=PRODUCTION_QA_CAPABILITY_ID
        or routing_decision.authorized_action!="RESEARCH"
        or routing_decision.selected_executor_binding!=capability.executor_binding):
        raise PermissionError("SENSORY_PRODUCTION_HARNESS_ROUTE_DENIED")
    if (not isinstance(payload,dict)
        or set(payload)!={"source_path","rights","profile","full_decode"}
        or payload["rights"]!="owned"
        or type(payload["full_decode"]) is not bool
        or payload["profile"] not in ("synthetic_ci_canary","br_no_gta_1080p_master")):
        raise PermissionError("SENSORY_PRODUCTION_PAYLOAD_DENIED")
    source=_admit(auth,payload["source_path"])
    evidence=analyze_render(source,profile=payload["profile"])
    entire=None
    if payload["full_decode"] and evidence["status"]=="TECHNICAL_SAMPLED_QA_PASS":
        entire=verify_full_decode(source,evidence)
    board=None
    if evidence["status"] in ("TECHNICAL_SAMPLED_QA_PASS","TECHNICAL_QA_FAIL"):
        from app.services.br_production_readiness_board_v10 import diagnose_technical_readiness
        board=diagnose_technical_readiness(evidence)
    return {
        "schema_version":"BRHarnessProductionForensicsExecution/v12",
        "capability_id":PRODUCTION_QA_CAPABILITY_ID,
        "status":"TECHNICAL_RESEARCH_EVIDENCE_ONLY",
        "authorization_id":auth.authorization_id,
        "execution_id":auth.execution_id,
        "evidence":evidence,
        "full_decode_evidence":entire,
        "production_readiness_board":board,
        "br_owner_v1_approval":"NOT_VERIFIED",
        "real_20_minute_episode_verified":False,
        "human_review_approved":False,
        "production_ready":False,
        "publication":"FORBIDDEN",
        "memory_write":"NOT_ATTEMPTED",
        "authority":"DEEPSEEK_HARNESS",
    }
