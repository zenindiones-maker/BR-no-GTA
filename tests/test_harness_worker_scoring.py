from dataclasses import replace
from datetime import datetime,timezone,timedelta
from app.services.harness_worker_plane import AgentCapability,AgentCapabilityManifest,CapabilityCertification,WorkerRegistration,digest
from app.services.harness_worker_scheduler import CapabilityScheduler,TaskDefinition,RoutingEvidenceSnapshot
from app.services.harness_git_transaction_store import canonical_bytes
def reg(w):
 m=AgentCapabilityManifest(w,w,"SEMANTIC","b1",(AgentCapability("cap","1"),),("ROLE",),("AGENT",),("TaskExecutionEnvelope/v1",),("TaskExecutionEvidence/v1",),("op",),"READ_ONLY",("r",),(),False,False,False,False,(),(),10,1000,("SHORT",),"x","h")
 m=replace(m,manifest_sha256=digest({k:v for k,v in __import__("dataclasses").asdict(m).items() if k!="manifest_sha256"}))
 now=datetime.now(timezone.utc);cert=CapabilityCertification(w,"b1","cap","1","run",1,"REAL_CANARY","TaskExecutionEnvelope/v1","TaskExecutionEvidence/v1","READ_ONLY",True,1,"",(now-timedelta(minutes=1)).isoformat(),(now+timedelta(days=1)).isoformat())
 cert=replace(cert,certification_hash=digest({k:v for k,v in __import__("dataclasses").asdict(cert).items() if k!="certification_hash"}));return WorkerRegistration(m,cert)
def task():return TaskDefinition("t","k","cap","1","ROLE","AGENT","TaskExecutionEnvelope/v1","TaskExecutionEvidence/v1",(),(),("op",),"READ_ONLY",("r",),(),None,5,100,1000,"B","S","N",())
def snap(rows):
 return RoutingEvidenceSnapshot.create(decision_as_of="2026-09-26T12:00:00+00:00",worker_evidence={k:{"competence":v,"health":100,"task_success":80,"certification_freshness":100,"latency_efficiency_score":80,"cost_efficiency_score":100} for k,v in rows.items()})
def test_higher_evidence_score_beats_lexicographic_name():
 a,z=reg("worker-A"),reg("worker-Z");s=CapabilityScheduler((a,z),evidence_snapshot=snap({"worker-A":10,"worker-Z":90}));assert s.route(mission_id="m",plan_id="p",plan_revision=1,task=task()).selected_worker=="worker-Z"
def test_routing_replay_is_byte_identical():
 regs=(reg("x"),reg("y"));s=CapabilityScheduler(regs,evidence_snapshot=snap({"x":70,"y":70}));a=s.route(mission_id="m",plan_id="p",plan_revision=1,task=task());b=s.route(mission_id="m",plan_id="p",plan_revision=1,task=task());assert canonical_bytes(__import__("dataclasses").asdict(a))==canonical_bytes(__import__("dataclasses").asdict(b))

def test_tampered_routing_evidence_snapshot_fails_closed():
 import pytest
 r=reg("x");snapshot=snap({"x":70});snapshot.worker_evidence["x"]["competence"]=99
 with pytest.raises(ValueError,match="ROUTING_EVIDENCE_SNAPSHOT_HASH_INVALID"):
  CapabilityScheduler((r,),evidence_snapshot=snapshot).route(mission_id="m",plan_id="p",plan_revision=1,task=task())

def test_tampered_provider_and_tool_availability_fail_closed():
 import pytest
 r=reg("x")
 for field in ("provider_availability","tool_availability"):
  snapshot=snap({"x":70});getattr(snapshot,field)["unexpected"]=True
  with pytest.raises(ValueError,match="ROUTING_EVIDENCE_SNAPSHOT_HASH_INVALID"):
   CapabilityScheduler((r,),evidence_snapshot=snapshot).route(mission_id="m",plan_id="p",plan_revision=1,task=task())

def test_routing_decision_binds_content_addressed_snapshot():
 r=reg("x");snapshot=snap({"x":70});d=CapabilityScheduler((r,),evidence_snapshot=snapshot).route(mission_id="m",plan_id="p",plan_revision=1,task=task())
 assert d.evidence_snapshot_hash==snapshot.snapshot_hash
 assert d.evidence_snapshot_ref=="objects/routing-evidence/sha256/"+snapshot.snapshot_hash+".json"

