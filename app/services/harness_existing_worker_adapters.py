from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope

def payload(e:TaskExecutionEnvelope)->dict[str,Any]:
 return {"mission_id":e.mission_id,"goal_id":e.human_goal_id,"task_id":e.task_id,"task":e.semantic_task_key,"input_refs":list(e.input_refs),"context":{"plan_id":e.plan_id,"plan_revision":e.plan_revision,"plan_hash":e.plan_hash,"trace_id":e.trace_id}}

@dataclass
class AgentOfficeWorkerAdapter:
 manifest:Any;invoke:Any
 def describe(self):return self.manifest
 def preflight(self,e):return {"PREFLIGHT":"PASS"}
 def execute(self,e):return self.invoke(e,payload(e))
 def normalize_evidence(self,e,r):
  from hashlib import sha256
  from app.services.harness_git_transaction_store import canonical_bytes
  from app.contracts.harness_specialized_worker_contracts import TaskExecutionEvidence
  if isinstance(r,TaskExecutionEvidence):return r
  raw={"schema":"TaskExecutionEvidence/v1","mission_id":e.mission_id,"plan_id":e.plan_id,"plan_revision":e.plan_revision,"task_id":e.task_id,"attempt_id":e.attempt_id,"capability_id":e.required_capability,"capability_version":e.required_capability_version,"worker_id":self.manifest.worker_id,"worker_build_id":self.manifest.worker_build_id,"completion_status":str((r or {}).get("status") or "COMPLETED"),"typed_output_refs":tuple((r or {}).get("typed_output_refs") or ()),"partial_refs":tuple((r or {}).get("partial_refs") or ()),"provider_id":(r or {}).get("provider_id"),"model_id":(r or {}).get("model_id"),"provider_call_count":int((r or {}).get("provider_call_count",0)),"agent_call_count":int((r or {}).get("agent_call_count",1)),"executed_operations":tuple((r or {}).get("executed_operations") or ()),"raw_exception_type":(r or {}).get("raw_exception_type"),"raw_error_code":(r or {}).get("raw_error_code"),"observed_metrics":dict((r or {}).get("observed_metrics") or {}),"checkpoint_refs":tuple((r or {}).get("checkpoint_refs") or ())}
  raw["evidence_hash"]=sha256(canonical_bytes(raw)).hexdigest()
  return TaskExecutionEvidence(**{k:v for k,v in raw.items() if k!="schema"})

@dataclass
class AddyWorkerAdapter(AgentOfficeWorkerAdapter):pass
@dataclass
class ResearchWorkerAdapter(AgentOfficeWorkerAdapter):pass
@dataclass
class SemanticWorkerAdapter(AgentOfficeWorkerAdapter):pass
@dataclass
class IndependentReviewWorkerAdapter(AgentOfficeWorkerAdapter):pass
@dataclass
class MediaWorkerAdapter(AgentOfficeWorkerAdapter):pass
@dataclass
class RenderWorkerAdapter(AgentOfficeWorkerAdapter):pass
@dataclass
class HermesWorkerAdapter(AgentOfficeWorkerAdapter):
 def execute(self,e):
  p=payload(e);p["delegated_subgraph_only"]=True
  return self.invoke(e,p)
