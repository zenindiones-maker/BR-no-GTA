"""V19: deterministic, abstaining specialist policy plane over EXISTING V17/V18.

No independent authority, model installation, remote ledger access or learning.
Operational readiness is evidence-bound, not inferred from a registry entry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.services.br_specialist_intelligence_v17 import SPEC as VISUAL_SPEC, execute_specialist
from app.services.br_owner_delivery_reconcile_specialist_v18 import observe_remote_ledger

SCHEMA="BRSpecialistDecision/v19"
SPEC_SCHEMA="BRSpecialistPolicySpec/v19"

@dataclass(frozen=True)
class SpecialistPolicy:
    specialist_id:str
    version:str
    domain:str
    operation:str
    tool_capability_id:str
    source_spec:str
    model_id:str
    knowledge_kind:str
    verified_level:str
    human_approval_required:bool
    authority:str="DEEPSEEK_HARNESS_ONLY"
    writable_learning:bool=False
    publication_authority:bool=False
    cost_policy:str="NO_REMOTE_PAID_ADMISSION"

POLICIES=(
    SpecialistPolicy(
        specialist_id="br.audiovisual.timeline-forensics",
        version="17.0.0",domain="audiovisual",
        operation="observe_original_scene_transitions",
        tool_capability_id="reverse-engineering.multimodal.sensory-pixels-v12",
        source_spec="docs/architecture/br-specialist-intelligence-v17.md",
        model_id="NONE_DETERMINISTIC_BASELINE",
        knowledge_kind="PROCEDURAL_LOCAL_REVIEWED",
        verified_level="VERIFIED_ON_CONTROLLED_SIX_SECOND_FIXTURES",
        human_approval_required=False,
    ),
    SpecialistPolicy(
        specialist_id="br.owner-voice.delivery-integrity",
        version="18.0.0",domain="owner-voice-ledger",
        operation="reconcile_private_delivery",
        tool_capability_id="owner-voice.ledger-readonly-v18",
        source_spec="docs/architecture/br-specialist-delivery-v18.md",
        model_id="NONE_DETERMINISTIC_BASELINE",
        knowledge_kind="PROCEDURAL_LOCAL_REVIEWED",
        verified_level="CONNECTED_UNIT_TESTED_AND_READBACK_REPORTED_SEPARATELY",
        human_approval_required=True,
    ),
)
OPERATIONS={spec.operation:spec for spec in POLICIES}


def _hash(data:Any)->str:
    return sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,
        allow_nan=False,separators=(",",":")).encode()).hexdigest()


def policy_inventory(root:Path)->dict[str,Any]:
    """Content-addressed local procedure inventory, no RAG or tool calls."""
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("SPECIALIST_KNOWLEDGE_ROOT_INVALID")
    records=[]
    for spec in POLICIES:
        file=(root/spec.source_spec).resolve(strict=True)
        if root.resolve() not in file.parents or file.is_symlink() or not file.is_file():
            raise PermissionError("SPECIALIST_KNOWLEDGE_SCOPE_DENIED")
        content=file.read_bytes()
        if not 200<=len(content)<=100_000:
            raise ValueError("SPECIALIST_KNOWLEDGE_INVALID_SIZE")
        records.append({
            **asdict(spec),
            "source_id":spec.source_spec,
            "source_sha256":sha256(content).hexdigest(),
            "source_bytes":len(content),
            "knowledge_trust":"EXISTING_DEVELOPMENT_SPEC_UNPROMOTED",
            "model_run_verified":False,
            "license_of_new_model":"NOT_APPLICABLE_NO_MODEL_INSTALLED",
        })
    out={"schema_version":"BRSpecialistPolicyInventory/v19",
         "specialists":records,"count":len(records),
         "new_model_installed":False,"learning_promoted":False}
    out["receipt_sha256"]=_hash(out)
    return out


def select(*,operation:str,rights:str,file_extension:str,
           provider_ready:bool,resource_admitted:bool,
           remote_ledger_grant:bool=False,uncertainty:float=0.0,
           consequence:str="LOW")->dict[str,Any]:
    """No natural language may redefine an operation or grant permission."""
    if (type(uncertainty) not in (int,float) or not 0<=uncertainty<=1
        or consequence not in ("LOW","MEDIUM","HIGH","CRITICAL")
        or type(provider_ready) is not bool
        or type(resource_admitted) is not bool
        or type(remote_ledger_grant) is not bool):
        raise ValueError("SPECIALIST_ROUTER_ARGUMENTS_INVALID")
    spec=OPERATIONS.get(operation) if isinstance(operation,str) else None
    reason="NO_MATCHING_VERIFIED_SPECIALIST"
    matched=False
    if spec is not None:
        if not provider_ready or not resource_admitted:
            reason="PROVIDER_OR_RESOURCE_NOT_ATTESTED"
        elif uncertainty>0.25 or consequence in ("HIGH","CRITICAL"):
            reason="UNCERTAIN_OR_HIGH_CONSEQUENCE_ESCALATE"
        elif spec.domain=="audiovisual":
            if rights=="owned" and file_extension.lower()==".mp4":
                matched=True
                reason="OWNED_SCOPED_MP4_MATCH"
            else:
                reason="MEDIA_RIGHTS_OR_TYPE_NOT_AUTHORIZED"
        elif spec.domain=="owner-voice-ledger":
            # Deliberately route to HUMAN/HARNESS authorization only.
            # No registration in GlobalCapabilityRegistry for private ledger.
            reason=("PRIVATE_LEDGER_MANUAL_HARNESS_AUTH_REQUIRED"
                    if not remote_ledger_grant else
                    "PRIVATE_LEDGER_EXPLICIT_OPERATOR_EXECUTION_REQUIRED")
    selected=spec if matched else None
    result={
        "schema_version":SCHEMA,
        "status":"SELECTED" if matched else "ABSTAIN",
        "operation":operation if operation in OPERATIONS else "UNRECOGNIZED",
        "specialist_id":selected.specialist_id if selected else None,
        "capability_id":selected.tool_capability_id if selected else None,
        "model_id":selected.model_id if selected else None,
        "decision_level":"DETERMINISTIC_POLICY",
        "reason":reason,
        "escalation":"NONE" if matched else "HARNESS_OR_HUMAN_REVIEW",
        "tool_invoked":False,
        "model_invoked":False,
        "resource_admitted":resource_admitted,
        "remote_ledger_read_attempted":False,
        "fallback_to_paid":False,
        "new_permissions_granted":False,
        "production_promotion":False,
    }
    result["receipt_sha256"]=_hash(result)
    return result


def execute_selected_visual(*,selection:dict[str,Any],authorization:Any,
                            source:Path,private_workspace:Path,
                            knowledge_root:Path,task_id:str)->dict[str,Any]:
    """Reuse the tested V17 execution. Never call ledger on its behalf."""
    if (not isinstance(selection,dict) or selection.get("receipt_sha256")!=
        _hash({k:v for k,v in selection.items() if k!="receipt_sha256"})
        or selection.get("status")!="SELECTED"
        or selection.get("specialist_id")!=VISUAL_SPEC.specialist_id
        or selection.get("capability_id")!=VISUAL_SPEC.tool_capability_id
        or selection.get("reason")!="OWNED_SCOPED_MP4_MATCH"):
        raise PermissionError("SPECIALIST_ROUTER_DECISION_UNTRUSTED")
    outcome=execute_specialist(
        authorization=authorization,source=source,private_workspace=private_workspace,
        knowledge_root=knowledge_root,task_id=task_id,
    )
    if (outcome.get("state")!="VERIFIED_OBSERVATION_ONLY"
        or outcome.get("receipt_sha256")!=
        _hash({k:v for k,v in outcome.items() if k!="receipt_sha256"})
        or outcome.get("publication_authorized") is not False
        or outcome.get("learning_write")!="NOT_ATTEMPTED"
        or outcome.get("tool_execution")!="REAL_HARNESS_CAPABILITY_ADAPTER"):
        raise ValueError("SPECIALIST_ROUTER_POSTCONDITION_FAILED")
    return {
        "schema_version":"BRSpecialistRoutedExecution/v19",
        "selection_receipt_sha256":selection["receipt_sha256"],
        "execution_receipt_sha256":outcome["receipt_sha256"],
        "specialist_id":VISUAL_SPEC.specialist_id,
        "state":"VERIFIED_REAL_HARNESS_EXECUTION",
        "postcondition":outcome["postcondition"],
        "latency_seconds":outcome["runtime_seconds"],
        "model_id":"NONE_DETERMINISTIC_BASELINE",
        "paid_calls":0,
        "remote_ledger_read":False,
        "human_voice_approved":False,
        "full_episode_certified":False,
        "publish_authorized":False,
        "learning_write":"NOT_ATTEMPTED",
    }
