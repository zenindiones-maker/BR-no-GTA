from app.services.harness_durable_task_runtime import DurableTaskRuntime
from app.services.harness_task_runtime import TaskAttempt,TaskCheckpoint,TaskHeartbeat
class S:
 def __init__(self):
  self.h={"mission_id":"m","state_version":1,"active_plan_hash":"ph"};self.objects={};self.sha="H1"
 def snapshot(self,m):
  from types import SimpleNamespace
  return SimpleNamespace(mission_head=dict(self.h),head_sha=self.sha)
 def transact(self,**kw):
  self.h=dict(kw["mission_head"]);self.objects.update(kw.get("immutable_objects") or {});self.sha="H"+str(self.h["state_version"]);return self.sha
 def read_json(self,p,r):return self.objects.get(p)
def attempt():
 return TaskAttempt("m","p",1,"ph","T1","A1",1,"w","b","cap","1","route",(),"RUNNING",None,None,None,None,None,None,None,None,None,None,None)
def test_task_attempt_checkpoint_heartbeat_are_durable():
 s=S();rt=DurableTaskRuntime(s);_,ar=rt.persist_attempt(attempt());assert s.h["task_attempt_refs"]["T1:A1"]==ar
 cp=TaskCheckpoint("m","p","T1","A1","ih",("u1",),("u2",),("partial:x",),"b","1","ch");_,cr=rt.persist_checkpoint(cp);assert s.h["task_checkpoint_refs"]["T1:A1"]==cr
 hb=TaskHeartbeat("m","p","T1","A1","w","b",cr,"u1","1/2",1,"obs");_,hr=rt.persist_heartbeat(hb);assert s.h["task_heartbeat_refs"]["T1:A1"]==hr
def test_heartbeat_sequence_cannot_go_backwards():
 import pytest
 s=S();rt=DurableTaskRuntime(s);rt.persist_attempt(attempt());hb=TaskHeartbeat("m","p","T1","A1","w","b",None,None,None,2,"obs");rt.persist_heartbeat(hb)
 with pytest.raises(PermissionError,match="MONOTONIC"):rt.persist_heartbeat(TaskHeartbeat("m","p","T1","A1","w","b",None,None,None,1,"obs2"))
