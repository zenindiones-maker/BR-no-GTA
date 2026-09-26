from __future__ import annotations
from dataclasses import asdict,replace
from app.services.harness_durable_execution_v3 import immutable_ref
from app.services.harness_git_transaction_store import GitHubGitTransactionStore
from app.services.harness_task_runtime import TaskAttempt,TaskCheckpoint,TaskHeartbeat

class DurableTaskRuntime:
 def __init__(self,store:GitHubGitTransactionStore):self.store=store
 def persist_attempt(self,attempt:TaskAttempt)->tuple[str,str]:
  snap=self.store.snapshot(attempt.mission_id);head=dict(snap.mission_head or {})
  if not head or head.get("active_plan_hash")!=attempt.plan_hash:raise PermissionError("TASK_ATTEMPT_PLAN_NOT_CURRENT")
  payload=asdict(attempt);ref,_=immutable_ref("task-attempts",payload)
  refs=dict(head.get("task_attempt_refs") or {});key=f"{attempt.task_id}:{attempt.attempt_id}"
  existing=refs.get(key)
  if existing:
   previous=self.store.read_json(existing,snap.head_sha) or {}
   terminal={"COMPLETED","FAILED_TYPED","ABANDONED","REVIEWED"}
   allowed={"PENDING":{"READY"},"READY":{"ROUTED"},"ROUTED":{"DISPATCHED"},"DISPATCHED":{"CLAIMED"},"CLAIMED":{"RUNNING"},"RUNNING":{"COMPLETED","FAILED_TYPED","CHECKPOINTED","ABANDONED","REVIEW_REQUIRED"},"CHECKPOINTED":{"RESUMED","ABANDONED"},"RESUMED":{"RUNNING","COMPLETED","FAILED_TYPED","CHECKPOINTED","ABANDONED"},"REVIEW_REQUIRED":{"REVIEWED"}}
   prior=str(previous.get("status") or "")
   if prior in terminal and attempt.status!=prior:raise PermissionError("TASK_ATTEMPT_TERMINAL_STATE_IMMUTABLE")
   if attempt.status!=prior and attempt.status not in allowed.get(prior,set()):raise PermissionError("TASK_ATTEMPT_INVALID_TRANSITION")
  refs[key]=ref;head["task_attempt_refs"]=refs;head["state_version"]=int(head["state_version"])+1
  commit=self.store.transact(mission_id=attempt.mission_id,expected_head_sha=snap.head_sha,expected_state_version=int(snap.mission_head["state_version"]),mission_head=head,immutable_objects={ref:payload})
  return commit,ref
 def persist_checkpoint(self,checkpoint:TaskCheckpoint)->tuple[str,str]:
  snap=self.store.snapshot(checkpoint.mission_id);head=dict(snap.mission_head or {})
  key=f"{checkpoint.task_id}:{checkpoint.attempt_id}"
  if key not in dict(head.get("task_attempt_refs") or {}):raise PermissionError("CHECKPOINT_ATTEMPT_NOT_CANONICAL")
  payload=asdict(checkpoint);ref,_=immutable_ref("task-checkpoints",payload);refs=dict(head.get("task_checkpoint_refs") or {});refs[key]=ref;head["task_checkpoint_refs"]=refs;head["state_version"]=int(head["state_version"])+1
  commit=self.store.transact(mission_id=checkpoint.mission_id,expected_head_sha=snap.head_sha,expected_state_version=int(snap.mission_head["state_version"]),mission_head=head,immutable_objects={ref:payload});return commit,ref
 def persist_heartbeat(self,heartbeat:TaskHeartbeat)->tuple[str,str]:
  snap=self.store.snapshot(heartbeat.mission_id);head=dict(snap.mission_head or {});key=f"{heartbeat.task_id}:{heartbeat.attempt_id}"
  if key not in dict(head.get("task_attempt_refs") or {}):raise PermissionError("HEARTBEAT_ATTEMPT_NOT_CANONICAL")
  previous_ref=dict(head.get("task_heartbeat_refs") or {}).get(key)
  if previous_ref:
   previous=self.store.read_json(previous_ref,snap.head_sha) or {}
   if heartbeat.heartbeat_sequence<=int(previous.get("heartbeat_sequence",-1)):raise PermissionError("HEARTBEAT_SEQUENCE_NOT_MONOTONIC")
  payload=asdict(heartbeat);ref,_=immutable_ref("task-heartbeats",payload);refs=dict(head.get("task_heartbeat_refs") or {});refs[key]=ref;head["task_heartbeat_refs"]=refs;head["state_version"]=int(head["state_version"])+1
  commit=self.store.transact(mission_id=heartbeat.mission_id,expected_head_sha=snap.head_sha,expected_state_version=int(snap.mission_head["state_version"]),mission_head=head,immutable_objects={ref:payload});return commit,ref
