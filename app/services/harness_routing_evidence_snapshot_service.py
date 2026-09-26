from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
from typing import Any
from app.database import harness_learning_repository as learning_repo
from app.services.harness_git_transaction_store import canonical_bytes
from app.services.harness_worker_plane import WorkerRegistration
from app.services.harness_worker_scheduler import RoutingEvidenceSnapshot

class RoutingEvidenceSnapshotBuilder:
 def __init__(self,registrations:tuple[WorkerRegistration,...],*,provider_availability:dict[str,bool],tool_availability:dict[str,bool]):
  self.registrations=registrations;self.provider_availability=dict(provider_availability);self.tool_availability=dict(tool_availability)
 def build(self,*,decision_as_of:str)->RoutingEvidenceSnapshot:
  evidence={};refs=[]
  for reg in self.registrations:
   m=reg.manifest
   rows=learning_repo.list_competence(capability_id=next(iter(m.capabilities)).capability_id,agent_id=m.agent_id,limit=20)
   active=[r for r in rows if int(r.get("tested_cases") or 0)>0]
   if not active: continue
   tested=sum(int(r.get("tested_cases") or 0) for r in active);success=sum(int(r.get("success_count") or 0) for r in active)
   failures=sum(int(r.get("failure_count") or 0) for r in active);retries=sum(int(r.get("retry_count") or 0) for r in active);corrections=sum(int(r.get("human_correction_count") or 0) for r in active)
   latency=sum(float(r.get("total_latency_seconds") or 0) for r in active)/max(tested,1);cost=sum(float(r.get("total_cost") or 0) for r in active)/max(tested,1)
   source_hash=sha256(canonical_bytes(active)).hexdigest();refs.append("learning-competence:sha256:"+source_hash)
   cert=reg.certification
   cert_ref="none"
   if cert is not None:
    cert_ref="capability-certification:sha256:"+cert.certification_hash;refs.append(cert_ref)
   evidence[m.worker_id]={
    "competence":round(100*success/max(tested,1)),"health":100 if failures==0 else max(0,100-round(100*failures/max(tested,1))),
    "task_success":round(100*success/max(tested,1)),"recent_failure_penalty":round(100*failures/max(tested,1)),
    "retry_penalty":round(100*retries/max(tested,1)),"human_correction_penalty":round(100*corrections/max(tested,1)),
    "latency_efficiency_score":max(0,min(100,round(100/(1+latency)))),"cost_efficiency_score":max(0,min(100,round(100/(1+cost)))),
    "certification_freshness":100 if cert is not None else 0,"tested_cases":tested,"source_hash":source_hash,"certification_ref":cert_ref}
  return RoutingEvidenceSnapshot.create(decision_as_of=decision_as_of,worker_evidence=evidence,provider_availability=self.provider_availability,tool_availability=self.tool_availability,provenance_refs=tuple(sorted(set(refs))))

def immutable_snapshot_object(snapshot:RoutingEvidenceSnapshot)->tuple[str,bytes]:
 snapshot.validate();ref="objects/routing-evidence/sha256/"+snapshot.snapshot_hash+".json";return ref,canonical_bytes(asdict(snapshot))
