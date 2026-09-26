from __future__ import annotations
from dataclasses import dataclass
from typing import Any

TASK_STATES=("PENDING","READY","ROUTED","DISPATCHED","CLAIMED","RUNNING","COMPLETED","FAILED_TYPED","CHECKPOINTED","RESUMED","ABANDONED","REVIEW_REQUIRED","REVIEWED")
@dataclass(frozen=True)
class TaskAttempt:
 mission_id:str;plan_id:str;plan_revision:int;plan_hash:str;task_id:str;attempt_id:str;attempt_number:int
 selected_worker_id:str;worker_build_id:str;capability_id:str;capability_version:str;routing_decision_ref:str;policy_decision_refs:tuple[str,...]
 status:str;transport_identity:dict[str,Any]|None;dispatch_ref:str|None;claim_ref:str|None;checkpoint_ref:str|None;heartbeat_ref:str|None
 started_at_evidence:str|None;terminal_evidence:str|None;failure_episode_ref:str|None;result_evidence_ref:str|None;review_evidence_ref:str|None
 schema:str="TaskAttempt/v1"
 def __post_init__(self):
  if self.status not in TASK_STATES:raise ValueError("TASK_ATTEMPT_INVALID_STATUS")

@dataclass(frozen=True)
class TaskHeartbeat:
 mission_id:str;plan_id:str;task_id:str;attempt_id:str;worker_id:str;worker_build_id:str;checkpoint_ref:str|None
 last_completed_unit:str|None;progress_marker:str|None;heartbeat_sequence:int;observed_at_evidence:str;schema:str="TaskHeartbeat/v1"

@dataclass(frozen=True)
class TaskCheckpoint:
 mission_id:str;plan_id:str;task_id:str;attempt_id:str;input_hash:str;completed_units:tuple[str,...];residual_units:tuple[str,...]
 partial_output_refs:tuple[str,...];worker_build_id:str;capability_version:str;checkpoint_hash:str;schema:str="TaskCheckpoint/v1"
