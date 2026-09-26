from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
from app.contracts.harness_specialized_worker_contracts import PolicyDecision
from app.services.harness_durable_execution_v3 import immutable_ref
from app.services.harness_git_transaction_store import canonical_bytes
from app.services.harness_task_runtime import TaskAttempt
from app.services.harness_worker_scheduler import CapabilityScheduler,TaskDefinition

class HarnessMissionReconciler:
 def __init__(self,store,scheduler:CapabilityScheduler):self.store=store;self.scheduler=scheduler
 @staticmethod
 def ready_tasks(tasks:tuple[TaskDefinition,...],completed:set[str],active:set[str])->tuple[TaskDefinition,...]:
  return tuple(t for t in tasks if t.task_id not in completed|active and set(t.dependency_task_ids)<=completed)
 def route_ready(self,*,mission_id:str,plan_id:str,plan_revision:int,plan_hash:str,task:TaskDefinition,attempt_id:str,attempt_number:int):
  snap=self.store.snapshot(mission_id);head=dict(snap.mission_head or {})
  if head.get("active_plan_hash")!=plan_hash:raise PermissionError("RECONCILER_PLAN_NOT_CURRENT")
  route=self.scheduler.route(mission_id=mission_id,plan_id=plan_id,plan_revision=plan_revision,task=task)
  route_payload=asdict(route);route_ref,_=immutable_ref("routing-decisions",route_payload)
  input_hash=sha256(canonical_bytes({"state_version":head["state_version"],"task":asdict(task),"routing":route.input_hash})).hexdigest()
  policy=PolicyDecision(decision_id="eligibility:"+input_hash[:24],policy_id="worker-eligibility",policy_version=route.policy_version,decision_type="ROUTING",input_refs=(head["active_plan_ref"],),input_hash=input_hash,decision="SELECT:"+route.selected_worker,reason=route.reason,mission_id=mission_id,plan_id=plan_id,plan_revision=plan_revision,created_from_state_version=int(head["state_version"]),task_id=task.task_id)
  policy_payload=asdict(policy);policy_ref,_=immutable_ref("policy-decisions",policy_payload)
  reg=next(r for r in self.scheduler.registrations if r.manifest.worker_id==route.selected_worker)
  attempt=TaskAttempt(mission_id,plan_id,plan_revision,plan_hash,task.task_id,attempt_id,attempt_number,route.selected_worker,reg.manifest.worker_build_id,task.required_capability,task.required_capability_version,route_ref,(policy_ref,),"ROUTED",None,None,None,None,None,None,None,None,None,None,None)
  attempt_payload=asdict(attempt);attempt_ref,_=immutable_ref("task-attempts",attempt_payload)
  key=f"{task.task_id}:{attempt_id}";attempts=dict(head.get("task_attempt_refs") or {});attempts[key]=attempt_ref;head["task_attempt_refs"]=attempts;head["state_version"]=int(head["state_version"])+1
  commit=self.store.transact(mission_id=mission_id,expected_head_sha=snap.head_sha,expected_state_version=int(snap.mission_head["state_version"]),mission_head=head,immutable_objects={route_ref:route_payload,policy_ref:policy_payload,attempt_ref:attempt_payload})
  return commit,route_ref,policy_ref,attempt_ref,route
