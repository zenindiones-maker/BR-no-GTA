from __future__ import annotations
from dataclasses import asdict,dataclass
from hashlib import sha256
from typing import Any,Callable
from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope,FORBIDDEN_WORKER_AUTHORITY_FIELDS,TaskExecutionEvidence,FORBIDDEN_WORKER_AUTHORITY_FIELDS
from app.services.harness_git_transaction_store import canonical_bytes
from app.services.harness_worker_plane import AgentCapabilityManifest,CapabilityCertification,CapabilitySpec,WorkerRegistration
from app.services.harness_worker_scheduler import CapabilityScheduler,TaskDefinition

@dataclass
class ExistingExecutorAdapter:
 manifest:AgentCapabilityManifest
 executor:Callable[[TaskExecutionEnvelope],dict[str,Any]]
 provider_calls:int=0
 agent_calls:int=1
 def describe(self):return self.manifest
 def preflight(self,envelope):
  if envelope.required_capability not in {c.capability_id for c in self.manifest.capabilities}:raise PermissionError("CAPABILITY_MISMATCH")
  return {"WORKER_EXECUTION_STARTED":"NO","PREFLIGHT":"PASS"}
 def execute(self,envelope):self.preflight(envelope);return self.executor(envelope)
 def normalize_evidence(self,envelope,result):
  if isinstance(result,dict) and set(result)&FORBIDDEN_WORKER_AUTHORITY_FIELDS:raise ValueError("WORKER_EVIDENCE_INVALID:AUTHORITY_FIELD")
  raw={"schema":"TaskExecutionEvidence/v1","mission_id":envelope.mission_id,"plan_id":envelope.plan_id,"plan_revision":envelope.plan_revision,"task_id":envelope.task_id,"attempt_id":envelope.attempt_id,"capability_id":envelope.required_capability,"capability_version":envelope.required_capability_version,"worker_id":self.manifest.worker_id,"worker_build_id":self.manifest.worker_build_id,"completion_status":str(result.get("status") or "COMPLETED"),"typed_output_refs":tuple(result.get("typed_output_refs") or ()),"partial_refs":tuple(result.get("partial_refs") or ()),"provider_id":result.get("provider_id"),"model_id":result.get("model_id"),"provider_call_count":int(result.get("provider_call_count",self.provider_calls)),"agent_call_count":int(result.get("agent_call_count",self.agent_calls)),"executed_operations":tuple(result.get("executed_operations") or ()),"raw_exception_type":result.get("raw_exception_type"),"raw_error_code":result.get("raw_error_code"),"observed_metrics":dict(result.get("observed_metrics") or {}),"checkpoint_refs":tuple(result.get("checkpoint_refs") or ())}
  raw["evidence_hash"]=sha256(canonical_bytes(raw)).hexdigest()
  return TaskExecutionEvidence(**{k:v for k,v in raw.items() if k!="schema"})

class WorkerExecutionPlane:
 def __init__(self,registrations):self.registrations=tuple(registrations);self.scheduler=CapabilityScheduler(self.registrations)
 def execute(self,*,mission_id,plan_id,plan_revision,task:TaskDefinition,envelope:TaskExecutionEnvelope,executor_worker_id=None):
  route=self.scheduler.route(mission_id=mission_id,plan_id=plan_id,plan_revision=plan_revision,task=task,executor_worker_id=executor_worker_id)
  reg=next(r for r in self.registrations if r.manifest.worker_id==route.selected_worker)
  if envelope.task_id!=task.task_id or envelope.required_capability!=route.selected_capability:raise PermissionError("TASK_EXECUTION_ENVELOPE_MISMATCH")
  result=reg.adapter.execute(envelope)
  evidence=reg.adapter.normalize_evidence(envelope,result)
  return route,evidence
 def execute_trusted(self,*,mission_id,plan_id,plan_revision,task:TaskDefinition,envelope:TaskExecutionEnvelope,authority_context:dict,executor_worker_id=None):
  route=self.scheduler.route(mission_id=mission_id,plan_id=plan_id,plan_revision=plan_revision,task=task,executor_worker_id=executor_worker_id)
  reg=next(r for r in self.registrations if r.manifest.worker_id==route.selected_worker)
  from app.services.harness_trusted_task_envelope import TrustedTaskEnvelopeValidator
  TrustedTaskEnvelopeValidator.validate(envelope=envelope,head=authority_context["head"],grant=authority_context["grant"],continuation=authority_context["continuation"],claim=authority_context.get("claim"),task=task,route=route,registration=reg)
  result=reg.adapter.execute(envelope)
  evidence=reg.adapter.normalize_evidence(envelope,result)
  return route,evidence
