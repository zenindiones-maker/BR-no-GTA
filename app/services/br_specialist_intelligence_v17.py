"""V17 first domain specialist: repeatably verified, read-only AV observation.

This is a capability configuration + an actual Harness executor, not a new
authority, model download, self-training service, or pseudo-agent persona.
The model may suggest the typed operation; the Harness alone routes/executes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any
import json
import re

from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest, route_harness_request,
)
from app.services.br_harness_sensory_authorization_v12 import CAPABILITY_ID as PIXEL_CAPABILITY

SCHEMA="BRSpecialistExecutionEvidence/v1"
REGISTRY_SCHEMA="BRSpecialistSpecification/v1"
ALLOWED_OPERATION="observe_original_scene_transitions"
SPEC_ID="br.audiovisual.timeline-forensics"
SOURCE_GUIDE=Path("docs/architecture/br-grounded-visual-v16.md")
_SHA=re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class SpecialistSpec:
    schema_version:str=REGISTRY_SCHEMA
    specialist_id:str=SPEC_ID
    version:str="17.0.0"
    domain:str="production-multimodal-observation"
    subdomain:str="owned-mp4-shot-transition-evidence"
    responsibilities:tuple[str,...]=(ALLOWED_OPERATION,)
    exclusions:tuple[str,...]=(
        "BR_OWNER_V1_SPEAKER_IDENTITY","TELEGRAM_DELIVERY",
        "REAL_EPISODE_APPROVAL","ARTIST_RECOGNITION",
        "EXTERNAL_BROWSER","AUTONOMOUS_TRAINING","PUBLICATION",
    )
    approved_model_candidates:tuple[str,...]=("existing-model-by-Harness-only",)
    selected_model:str="NONE_DETERMINISTIC_BASELINE"
    tool_capability_id:str=PIXEL_CAPABILITY
    authorized_action:str="RESEARCH"
    required_knowledge:str=str(SOURCE_GUIDE)
    input_contract:str="owned local MP4 + Harness scope + private scratch + scene_scan true"
    output_contract:str=SCHEMA
    evaluation_suite:str="tests/test_specialist_intelligence_v17.py"
    quality_criteria:str="10/10 positive and 10/10 negative repeated real MP4 evaluations; zero unauthorized effects"
    budget:str="20 bounded single-run observations; no remote inference or paid provider"
    promotion_status:str="CANDIDATE_NOT_PROMOTED"
    escalation_rule:str="ABSTAIN on unsupported tasks, private owner voice or unclear evidence"


SPEC=SpecialistSpec()


def _digest(obj:Any)->str:
    return sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),
                             ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def knowledge_receipt(root:Path)->dict[str,Any]:
    """Only a local, reviewed protocol is admitted as procedural knowledge."""
    if not isinstance(root,Path) or not root.is_absolute():
        raise ValueError("SPECIALIST_KNOWLEDGE_ROOT_INVALID")
    p=(root/SOURCE_GUIDE).resolve(strict=True)
    if root.resolve() not in p.parents or p.is_symlink() or not p.is_file():
        raise PermissionError("SPECIALIST_KNOWLEDGE_PATH_UNTRUSTED")
    body=p.read_bytes()
    if not 200<=len(body)<=100_000:
        raise ValueError("SPECIALIST_KNOWLEDGE_SIZE_INVALID")
    return {
        "source_id":"BR-V16-APPROVED-LOCAL-PROTOCOL",
        "publisher":"owner-project",
        "source_type":"PROCEDURAL",
        "content_sha256":sha256(body).hexdigest(),
        "source_version":"V16",
        "trust_level":"REVIEWED_PROJECT_DOCUMENT_CANDIDATE",
        "applicable_tool_version":"br_harness_visual_timeline_v16",
        "retrieval_method":"LOCAL_EXACT_PATH_NO_GENERATIVE_RAG",
        "agent_instruction_authority":False,
    }


def select_specialist(
    *, operation:str,rights:str,extension:str,provider_ready:bool=True
)->dict[str,Any]:
    """Deterministic primary selector, no natural language privilege grants."""
    ready=(
        operation==ALLOWED_OPERATION
        and rights=="owned" and extension.lower()==".mp4"
        and type(provider_ready) is bool and provider_ready
    )
    return {
        "status":"SELECTED" if ready else "ABSTAIN",
        "specialist_id":SPEC_ID if ready else None,
        "capability_id":PIXEL_CAPABILITY if ready else None,
        "model_invoked":False,
        "tool_invoked":False,
        "fallback_allowed":False,
        "reason":"OWNED_MP4_TIMELINE_MATCH" if ready else "UNSUPPORTED_OR_UNVERIFIED_PREREQUISITE",
        "escalation":"HARNESS_POLICY_REVIEW_REQUIRED" if not ready else "NONE",
        "authority_changed":False,
    }


def verify_visual_result(execution:dict[str,Any])->dict[str,Any]:
    """Independent postcondition: real pixels + same-source timestamped frames."""
    if not isinstance(execution,dict) or execution.get("publication")!="FORBIDDEN":
        raise ValueError("SPECIALIST_EXECUTOR_BOUNDARY_VIOLATION")
    pix=execution.get("evidence")
    timeline=execution.get("visual_timeline_evidence")
    if not isinstance(pix,dict) or not isinstance(timeline,dict):
        raise ValueError("SPECIALIST_ACTUAL_PIXEL_OR_TIMELINE_EVIDENCE_MISSING")
    if (pix.get("status")!="PIXELS_DECODED_AND_MEASURED"
        or pix.get("media_kind")!="owner_video_mp4"
        or not _SHA.fullmatch(str(pix.get("source_sha256","")))
        or not _SHA.fullmatch(str(pix.get("receipt_sha256","")))):
        raise ValueError("SPECIALIST_PIXEL_PROOF_INVALID")
    if _digest({k:v for k,v in pix.items() if k!="receipt_sha256"})!=pix["receipt_sha256"]:
        raise ValueError("SPECIALIST_PIXEL_RECEIPT_DRIFT")
    if (timeline.get("status")!="SCOPED_VIDEO_TRANSITIONS_MEASURED"
        or timeline.get("source_sha256")!=pix["source_sha256"]
        or timeline.get("pixel_receipt_sha256")!=pix["receipt_sha256"]
        or not _SHA.fullmatch(str(timeline.get("sha256","")))
        or _digest({k:v for k,v in timeline.items() if k!="sha256"})!=timeline["sha256"]):
        raise ValueError("SPECIALIST_TIMELINE_RECEIPT_DRIFT")
    if (timeline.get("semantically_interpreted") is not False
        or timeline.get("publisher_authorized") is not False
        or timeline.get("owner_identity_certified") is not False
        or pix.get("semantic_scene_understood") is not False
        or execution.get("agents_can_consume_private_frames") is not False):
        raise ValueError("SPECIALIST_FALSE_SEMANTIC_OR_VOICE_CLAIM")
    if (not isinstance(timeline.get("candidate_transition_count"),int)
        or timeline["candidate_transition_count"]<0
        or not isinstance(timeline.get("candidate_transition_times_seconds"),list)
        or timeline["candidate_transition_count"]!=len(timeline["candidate_transition_times_seconds"])):
        raise ValueError("SPECIALIST_TIMELINE_COUNT_INVALID")
    duration=timeline.get("windows")
    if not isinstance(duration,list) or not 1<=len(duration)<=3:
        raise ValueError("SPECIALIST_TIMELINE_WINDOWS_INVALID")
    return {
        "verified":True,"verification":"PIXELS_AND_TIMELINE_TWO_RECEIPTS_MATCH",
        "source_sha256":pix["source_sha256"],
        "pixel_receipt_sha256":pix["receipt_sha256"],
        "timeline_receipt_sha256":timeline["sha256"],
        "cut_candidates":timeline["candidate_transition_count"],
        "cut_seconds":list(timeline["candidate_transition_times_seconds"]),
        "semantic_scene_understood":False,
        "full_episode_approved":False,
        "owner_voice_approved":False,
    }


def execute_specialist(
    *, authorization:Any, source:Path, private_workspace:Path,
    knowledge_root:Path,
    task_id:str,
)->dict[str,Any]:
    """Actual existing Harness CapabilityAdapter, not direct FFmpeg CLI access."""
    if not isinstance(task_id,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{4,80}",task_id):
        raise ValueError("SPECIALIST_TASK_ID_INVALID")
    selection=select_specialist(
        operation=ALLOWED_OPERATION,rights="owned",extension=source.suffix,
    )
    if selection["status"]!="SELECTED":
        raise PermissionError("SPECIALIST_ABSTAINED")
    knowledge=knowledge_receipt(knowledge_root)
    routed=route_harness_request(HarnessRoutingRequest(
        intent="Analyze actual owner MP4 pixels and scene transitions in bounded windows",
        authorized_action="RESEARCH",
        domain=SPEC.domain,
        required_capability_id=PIXEL_CAPABILITY,
        fallback_allowed=False,provider_required=False,learning_required=False,
        task_id=task_id,
    ))
    start=perf_counter()
    run=CapabilityAdapter().execute(
        authorization=authorization,
        task_envelope=TaskEnvelope(
            task_id=task_id,capability_id=PIXEL_CAPABILITY,action="RESEARCH",
            objective="Inspect original local video with exact timestamped evidence",
            allowed_tools=("ffmpeg","ffprobe","pillow"),
            cost_budget=0.0,retry_budget=0,
        ),
        routing_decision=routed,
        payload={
            "source_path":str(source),"private_workspace":str(private_workspace),
            "kind":"owner_video_mp4","rights":"owned","scene_scan":True,
        },
    )
    measured=verify_visual_result(run.result)
    output={
        "schema_version":SCHEMA,
        "task_id":task_id,
        "specialist_id":SPEC_ID,
        "specialist_version":SPEC.version,
        "model_id":"NONE_DETERMINISTIC_BASELINE",
        "model_downloads":0,
        "knowledge":knowledge,
        "selection":selection,
        "routing_id":routed.routing_id,
        "selected_capability_id":routed.selected_capability_id,
        "runtime_seconds":round(perf_counter()-start,4),
        "tool_execution":"REAL_HARNESS_CAPABILITY_ADAPTER",
        "postcondition":measured,
        "state":"VERIFIED_OBSERVATION_ONLY",
        "voice_identity_verified":False,
        "whole_episode_certified":False,
        "publication_authorized":False,
        "learning_write":"NOT_ATTEMPTED",
        "production_mutation":False,
        "policy_authority":"DEEPSEEK_HARNESS",
    }
    output["receipt_sha256"]=_digest(output)
    return output
