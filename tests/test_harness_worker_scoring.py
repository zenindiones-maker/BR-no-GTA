from dataclasses import replace
from datetime import datetime,timezone,timedelta
from app.services.harness_worker_plane import AgentCapability,AgentCapabilityManifest,CapabilityCertification,WorkerRegistration,digest
from app.services.harness_worker_scheduler import CapabilityScheduler,TaskDefinition
def reg(w):
 m=AgentCapabilityManifest(w,w,"SEMANTIC","b1",(AgentCapability("cap","1"),),("ROLE",),("AGENT",),("TaskExecutionEnvelope/v1",),("TaskExecutionEvidence/v1",),("op",),"READ_ONLY",("r",),(),False,False,False,False,(),(),10,1000,("SHORT",),"x","h")
 m=replace(m,manifest_sha256=digest({k:v for k,v in __import__("dataclasses").asdict(m).items() if k!="manifest_sha256"}))
 now=datetime.now(timezone.utc);cert=CapabilityCertification(w,"b1","cap","1","run",1,"REAL_CANARY","TaskExecutionEnvelope/v1","TaskExecutionEvidence/v1","READ_ONLY",True,1,"",(now-timedelta(minutes=1)).isoformat(),(now+timedelta(days=1)).isoformat())
 cert=replace(cert,certification_hash=digest({k:v for k,v in __import__("dataclasses").asdict(cert).items() if k!="certification_hash"}));return WorkerRegistration(m,cert)
def task():return TaskDefinition("t","k","cap","1","ROLE","AGENT","TaskExecutionEnvelope/v1","TaskExecutionEvidence/v1",(),(),("op",),"READ_ONLY",("r",),(),None,5,100,1000,"B","S","N",())
def test_higher_evidence_score_beats_lexicographic_name():
 a,z=reg("worker-A"),reg("worker-Z");s=CapabilityScheduler((a,z),performance={"worker-A":{"competence":10},"worker-Z":{"competence":90}});assert s.route(mission_id="m",plan_id="p",plan_revision=1,task=task()).selected_worker=="worker-Z"
def test_routing_replay_is_byte_identical():
 regs=(reg("x"),reg("y"));s=CapabilityScheduler(regs,performance={"x":{"competence":70},"y":{"competence":70}});a=s.route(mission_id="m",plan_id="p",plan_revision=1,task=task());b=s.route(mission_id="m",plan_id="p",plan_revision=1,task=task());assert a==b
