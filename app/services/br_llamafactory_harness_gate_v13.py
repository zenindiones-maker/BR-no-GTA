"""Read-only Harness gate for the LLaMA-Factory admission plane."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from app.services.harness_authorization_service import validate_harness_authorization

CAPABILITY_ID = "learning.llamafactory.dataset-admission-v13"


def execute_authorized_llamafactory_admission(
    *, authorization:Any, routing_decision:Any, payload:dict[str,Any],
)->dict[str,Any]:
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    from app.services.br_llamafactory_training_admission_v13 import prepare_readonly_plan

    auth=validate_harness_authorization(
        authorization,expected_action="RESEARCH",
        expected_subject=f"capability:{CAPABILITY_ID}",
    )
    capability=GLOBAL_CAPABILITY_REGISTRY.get(CAPABILITY_ID)
    if capability is None or not capability.execution_enabled:
        raise PermissionError("LLAMA_FACTORY_ADMISSION_CAPABILITY_UNAVAILABLE")
    if (routing_decision.selected_capability_id!=CAPABILITY_ID
        or routing_decision.authorized_action!="RESEARCH"
        or routing_decision.selected_executor_binding!=capability.executor_binding):
        raise PermissionError("LLAMA_FACTORY_HARNESS_ROUTING_MISMATCH")
    if (not isinstance(payload,dict)
        or set(payload)!={"dataset_path","rights","model_id"}
        or payload["rights"]!="owned"
        or not isinstance(payload["dataset_path"],str)
        or not isinstance(payload["model_id"],str)):
        raise PermissionError("LLAMA_FACTORY_HARNESS_PAYLOAD_FORBIDDEN")
    roots=auth.lineage.get("allowed_media_roots")
    if not isinstance(roots,list) or not 1<=len(roots)<=8:
        raise PermissionError("LLAMA_FACTORY_SCOPE_MISSING")
    permitted=tuple(Path(x) for x in roots if isinstance(x,str))
    result=prepare_readonly_plan(
        dataset_path=Path(payload["dataset_path"]),
        allowed_roots=permitted,
        model_id=payload["model_id"],
    )
    return {
        "schema_version":"BRHarnessLlamaFactoryAdmissionExecution/v1",
        "status":"RESEARCH_DATASET_ADMITTED_NO_TRAINING",
        "capability_id":CAPABILITY_ID,
        "authorization_id":auth.authorization_id,
        "execution_id":auth.execution_id,
        "evidence":result,
        "owner_voice_training_access":"FORBIDDEN",
        "model_training_executed":False,
        "production_mutation":False,
        "publication":"FORBIDDEN",
        "learning_write":"NOT_ATTEMPTED",
        "authority":"DEEPSEEK_HARNESS",
    }
