from __future__ import annotations
from dataclasses import asdict,dataclass
from hashlib import sha256
from typing import Any
from datetime import datetime,timezone
from dataclasses import replace
from app.services.harness_worker_plane import digest
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
class WorkerScore:
 worker_id:str;competence:int;health:int;task_success:int;recent_failure_penalty:int;retry_penalty:int;human_correction_penalty:int;latency:int;cost:int;certification_freshness:int;total:int

@dataclass(frozen=True)
class WorkerScoringPolicy:
 version:str="worker-scoring/v1";competence_weight:int=30;health_weight:int=20;task_success_weight:int=20;certification_weight:int=10;latency_weight:int=10;cost_weight:int=10;failure_penalty_weight:int=20;retry_penalty_weight:int=10;human_correction_penalty_weight:int=10

@dataclass(frozen=True)
class RoutingDecision:
 mission_id:str;plan_id:str;plan_revision:int;task_id:str;eligible_candidates:tuple[str,...];rejected_candidates:tuple[CandidateDecision,...]
 candidate_scores:tuple[WorkerScore,...];selected_worker:str;selected_capability:str;provider_requirements:tuple[str,...];selected_provider:str|None;selected_model:str|None
 policy_version:str;scoring_policy_version:str;tie_break_reason:str;reason:str;input_hash:str;schema:str="RoutingDecision/v1"

class WorkerEligibilityEngine:
 def evaluate(self,task:TaskDefinition,reg:WorkerRegistration,*,executor_worker_id:str|None=None)->CandidateDecision:
  m=reg.manifest;c={x.capability_id:x.capability_version for x in m.capabilities}
  manifest_raw=asdict(m);manifest_hash=manifest_raw.pop("manifest_sha256")
  manifest_valid=manifest_hash==digest(manifest_raw)
  cert=reg.certification
  cert_valid=False
  if cert is not None:
   cert_raw=asdict(cert);cert_hash=cert_raw.pop("certification_hash")
   try: cert_not_expired=datetime.fromisoformat(cert.expires_at.replace("Z","+00:00"))>datetime.now(timezone.utc)
   except ValueError: cert_not_expired=False
   cert_valid=cert_hash==digest(cert_raw) and cert_not_expired and cert.worker_id==m.worker_id and cert.capability_id==task.required_capability and cert.capability_version==task.required_capability_version
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
   (manifest_valid,"MANIFEST_HASH_INVALID"),
   (cert_valid,"BUILD_NOT_CERTIFIED"),
   (cert is None or cert.worker_build_id==m.worker_build_id,"BUILD_NOT_CERTIFIED"),
   (cert is None or cert.success,"BUILD_NOT_CERTIFIED"),
   (not task.review_requirement or m.supports_review,"REVIEW_UNSUPPORTED"),
   (not task.review_requirement or executor_worker_id!=m.worker_id,"REVIEW_INDEPENDENCE_FAILED"),
  ]
  for ok,reason in checks:
   if not ok:return CandidateDecision(m.worker_id,False,reason)
  return CandidateDecision(m.worker_id,True,"ACCEPTED")

class CapabilityScheduler:
 def __init__(self,registrations:tuple[WorkerRegistration,...],*,performance:dict[str,dict[str,int]]|None=None,scoring_policy:WorkerScoringPolicy|None=None):
  self.registrations=registrations;self.engine=WorkerEligibilityEngine();self.performance=performance or {};self.scoring_policy=scoring_policy or WorkerScoringPolicy()
 def _score(self,reg:WorkerRegistration)->WorkerScore:
  p=self.performance.get(reg.manifest.worker_id,{})
  competence=max(0,min(100,int(p.get("competence",50))));health=max(0,min(100,int(p.get("health",100))));success=max(0,min(100,int(p.get("task_success",50))))
  failure=max(0,min(100,int(p.get("recent_failure_penalty",0))));retry=max(0,min(100,int(p.get("retry_penalty",0))));correction=max(0,min(100,int(p.get("human_correction_penalty",0))))
  latency=max(0,min(100,int(p.get("latency",50))));cost=max(0,min(100,int(p.get("cost",100))));fresh=max(0,min(100,int(p.get("certification_freshness",100))))
  w=self.scoring_policy;total=competence*w.competence_weight+health*w.health_weight+success*w.task_success_weight+fresh*w.certification_weight+latency*w.latency_weight+cost*w.cost_weight-failure*w.failure_penalty_weight-retry*w.retry_penalty_weight-correction*w.human_correction_penalty_weight
  return WorkerScore(reg.manifest.worker_id,competence,health,success,failure,retry,correction,latency,cost,fresh,total)
 def route(self,*,mission_id:str,plan_id:str,plan_revision:int,task:TaskDefinition,executor_worker_id:str|None=None)->RoutingDecision:
  decisions=tuple(self.engine.evaluate(task,r,executor_worker_id=executor_worker_id) for r in self.registrations)
  eligible=tuple(sorted(d.worker_id for d in decisions if d.accepted))
  if not eligible:raise RuntimeError("PRECONDITION_UNSATISFIED")
  regs=[r for r in self.registrations if r.manifest.worker_id in eligible];scores=tuple(sorted((self._score(r) for r in regs),key=lambda x:x.worker_id))
  best=max(s.total for s in scores);tied=tuple(sorted(s.worker_id for s in scores if s.total==best))
  selected=min(tied,key=lambda wid:sha256(canonical_bytes({"mission_id":mission_id,"plan_id":plan_id,"task_id":task.task_id,"worker_id":wid,"policy":self.scoring_policy.version})).hexdigest())
  reg=next(r for r in regs if r.manifest.worker_id==selected)
  payload={"mission_id":mission_id,"plan_id":plan_id,"plan_revision":plan_revision,"task":asdict(task),"candidates":[asdict(x) for x in decisions],"scores":[asdict(x) for x in scores],"scoring_policy":asdict(self.scoring_policy)}
  return RoutingDecision(mission_id,plan_id,plan_revision,task.task_id,eligible,tuple(d for d in decisions if not d.accepted),scores,selected,task.required_capability,reg.manifest.provider_requirements,None,None,"worker-routing/v2",self.scoring_policy.version,"STABLE_HASH" if len(tied)>1 else "HIGHEST_SCORE","hard eligibility then deterministic evidence score",sha256(canonical_bytes(payload)).hexdigest())
