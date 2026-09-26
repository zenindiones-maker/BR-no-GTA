from dataclasses import replace
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from app.services.harness_mission_reconciler_v3 import HarnessMissionReconciler
from app.services.harness_worker_plane import AgentCapabilityManifest,CapabilityCertification,CapabilitySpec,WorkerRegistration
from app.services.harness_worker_scheduler import CapabilityScheduler,TaskDefinition
class A:
 def describe(self):return None
class S:
 def __init__(self):self.sha="H";self.h={"state_version":1,"active_plan_hash":"ph","active_plan_ref":"plan"}
 def snapshot(self,m):return SimpleNamespace(head_sha=self.sha,mission_head=dict(self.h))
 def transact(self,**k):self.h=dict(k["mission_head"]);self.objects=k["immutable_objects"];return "H2"
def reg():
 m=AgentCapabilityManifest("a","worker-x","SPECIALIZED","b",(CapabilitySpec("cap","1"),),("ANALYSIS",),("DETERMINISTIC_WORKER",),("In/v1",),("Out/v1",),(),"READ_ONLY",(),(),False,False,False,True,(),(),4,1000,("SHORT",),"x","h","NONE").sealed()
 now=datetime.now(timezone.utc);c=CapabilityCertification("worker-x","b","cap","1","real-run",1,"REAL_DETERMINISTIC_CANARY","In/v1","Out/v1","READ_ONLY",True,1,"none",now.isoformat(),(now+timedelta(days=1)).isoformat()).sealed();return WorkerRegistration(m,A(),c)
def task(id="T1",deps=()):return TaskDefinition(id,id,"cap","1","ANALYSIS","DETERMINISTIC_WORKER","In/v1","Out/v1",(),deps,(),"READ_ONLY",(),(),None,1,100,1000,"NONE","PARALLEL_SAFE","NONE",())
def test_reconciler_derives_dependencies_and_persists_route_policy_attempt():
 s=S();r=HarnessMissionReconciler(s,CapabilityScheduler((reg(),)));assert [x.task_id for x in r.ready_tasks((task("T1"),task("T2",("T1",))),set(),set())]==["T1"]
 _,rr,pr,ar,route=r.route_ready(mission_id="m",plan_id="p",plan_revision=1,plan_hash="ph",task=task(),attempt_id="a1",attempt_number=1)
 assert route.selected_worker=="worker-x";assert rr in s.objects and pr in s.objects and ar in s.objects;assert s.h["task_attempt_refs"]["T1:a1"]==ar
