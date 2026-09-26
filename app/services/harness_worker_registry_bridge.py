from __future__ import annotations
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_executor_contract_service import registry_executor_is_task_adapter_compatible
from app.services.harness_worker_plane import AgentCapabilityManifest,CapabilitySpec

def manifest_from_capability_registry(capability_id:str,*,worker_build_id:str,input_schema:str="TaskExecutionEnvelope/v1",output_schema:str="TaskExecutionEvidence/v1")->AgentCapabilityManifest:
 r=GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
 if r is None:raise KeyError(capability_id)
 if str(r.capability_type).upper()=="PROVIDER":raise PermissionError("PROVIDER_IS_NOT_WORKER")
 if not r.execution_enabled:raise PermissionError("WORKER_EXECUTION_DISABLED")
 if not registry_executor_is_task_adapter_compatible(r.executor_binding):raise PermissionError("WORKER_EXECUTOR_BINDING_INCOMPATIBLE")
 return AgentCapabilityManifest(
  agent_id=str(r.agent_id or capability_id),worker_id=f"worker:{capability_id}",worker_kind=str(r.capability_type),worker_build_id=worker_build_id,
  capabilities=(CapabilitySpec(capability_id,str(r.version or "1")),),functional_roles=tuple(r.functional_roles or ("GENERAL",)),
  execution_kinds=(str(r.execution_kind or "CAPABILITY_WORKER"),),input_schemas=(input_schema,),output_schemas=(output_schema,),
  execution_operations=tuple(r.execution_operations or ()),side_effect_class=str(r.side_effect_class or "READ_ONLY"),
  read_scope_classes=tuple(r.default_read_scope or ()),write_scope_classes=tuple(r.default_write_scope or ()),
  supports_checkpoint=bool(r.supports_resume),supports_resume=bool(r.supports_resume),supports_review=bool(r.supports_review),supports_parallelism=bool(r.supports_parallelism),
  provider_requirements=tuple(() if str(r.provider_id or "") in {"","internal"} else (str(r.provider_id),)),tool_requirements=tuple(r.allowed_tools or ()),
  max_tool_call_budget=1000,max_context_tokens=262144,supported_timeout_classes=("BOUNDED",),executor_binding=str(r.executor_binding),health_contract=str(r.health_policy or "DEFAULT"),authority="NONE").sealed()
