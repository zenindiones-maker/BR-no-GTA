from __future__ import annotations
from dataclasses import asdict,dataclass
from hashlib import sha256
from typing import Any
from app.services.harness_git_transaction_store import canonical_bytes
from app.services.harness_worker_plane import WorkerRegistration

@dataclass(frozen=True)
class TaskDefinition:
 task_id:str;semantic_task_key:str;required_capability:str;required_capability_version:str;functional_role:str;execution_kind:str
 input_schema:str;expected_output_schema:str;input_refs:tuple[str,...];dependency_task_ids:tuple[str,...];required_operations:tuple[str,...]
 side_effect_class:str;read_scope:tuple[str,...];write_scope:tuple[str,...];review_requirement:str|None;tool_call_budget:int
 context_budget:int;time_budget_ms:int;retry_policy:str;parallelism_policy:str;checkpoint_policy:str;acceptance_criteria:tuple[str,...]
 schema:str="TaskDefinition/v1"

@dataclass(frozen=True)
class CandidateDecision:
 worker_id:str;accepted:bool;reason:str

@dataclass(frozen=True)
class RoutingDecision:
 mission_id:str;plan_id:str;plan_revision:int;task_id:str;eligible_candidates:tuple[str,...];rejected_candidates:tuple[CandidateDecision,...]
 selected_worker:str;selected_capability:str;provider_requirements:tuple[str,...];selected_provider:str|None;selected_model:str|None
 policy_version:str;reason:str;input_hash:str;schema:str="RoutingDecision/v1"

class WorkerEligibilityEngine:
 def evaluate(self,task:TaskDefinition,reg:WorkerRegistration,*,executor_worker_id:str|None=None)->CandidateDecision:
  m=reg.manifest;c={x.capability_id:x.capability_version for x in m.capabilities}
  checks=[
   (task.required_capability in c,"CAPABILITY_MISMATCH"),
   (c.get(task.required_capability)==task.required_capability_version,"CAPABILITY_VERSION_MISMATCH"),
   (task.functional_role in m.functional_roles,"FUNCTIONAL_ROLE_MISMATCH"),
   (task.execution_kind in m.execution_kinds,"EXECUTION_KIND_MISMATCH"),
   (task.input_schema in m.input_schemas,"INPUT_SCHEMA_MISMATCH"),
   (task.expected_output_schema in m.output_schemas,"OUTPUT_SCHEMA_MISMATCH"),
   (set(task.required_operations)<=set(m.execution_operations),"EXECUTION_OPERATION_MISMATCH"),
   (task.side_effect_class==m.side_effect_class,"SIDE_EFFECT_CLASS_MISMATCH"),
   (set(task.read_scope)<=set(m.read_scope_classes),"READ_SCOPE_MISMATCH"),
   (set(task.write_scope)<=set(m.write_scope_classes),"WRITE_SCOPE_MISMATCH"),
   (task.tool_call_budget<=m.max_tool_call_budget,"BUDGET_EXCEEDED"),
   (m.authority=="NONE","AUTHORITY_ESCALATION"),
   (reg.certification is not None,"BUILD_NOT_CERTIFIED"),
   (reg.certification is None or reg.certification.worker_build_id==m.worker_build_id,"BUILD_NOT_CERTIFIED"),
   (reg.certification is None or reg.certification.success,"BUILD_NOT_CERTIFIED"),
   (not task.review_requirement or m.supports_review,"REVIEW_UNSUPPORTED"),
   (not task.review_requirement or executor_worker_id!=m.worker_id,"REVIEW_INDEPENDENCE_FAILED"),
  ]
  for ok,reason in checks:
   if not ok:return CandidateDecision(m.worker_id,False,reason)
  return CandidateDecision(m.worker_id,True,"ACCEPTED")

class CapabilityScheduler:
 def __init__(self,registrations:tuple[WorkerRegistration,...]):self.registrations=registrations;self.engine=WorkerEligibilityEngine()
 def route(self,*,mission_id:str,plan_id:str,plan_revision:int,task:TaskDefinition,executor_worker_id:str|None=None)->RoutingDecision:
  decisions=tuple(self.engine.evaluate(task,r,executor_worker_id=executor_worker_id) for r in self.registrations)
  eligible=tuple(sorted(d.worker_id for d in decisions if d.accepted))
  if not eligible:raise RuntimeError("PRECONDITION_UNSATISFIED")
  selected=eligible[0]
  reg=next(r for r in self.registrations if r.manifest.worker_id==selected)
  payload={"mission_id":mission_id,"plan_id":plan_id,"plan_revision":plan_revision,"task":asdict(task),"candidates":[asdict(x) for x in decisions]}
  return RoutingDecision(mission_id,plan_id,plan_revision,task.task_id,eligible,tuple(d for d in decisions if not d.accepted),selected,task.required_capability,reg.manifest.provider_requirements,None,None,"worker-routing/v1","deterministic eligibility then stable evidence ranking",sha256(canonical_bytes(payload)).hexdigest())
