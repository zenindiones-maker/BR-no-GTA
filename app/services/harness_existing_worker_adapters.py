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
 def normalize_evidence(self,e,r):return r

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
