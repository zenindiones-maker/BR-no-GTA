from __future__ import annotations
from dataclasses import asdict
from app.contracts.harness_specialized_worker_contracts import TaskExecutionEnvelope
from app.services.harness_worker_scheduler import RoutingDecision,TaskDefinition
from app.services.harness_worker_plane import WorkerRegistration

class TrustedTaskEnvelopeValidator:
 @staticmethod
 def validate(*,envelope:TaskExecutionEnvelope,head:dict,grant:dict,continuation:dict,claim:dict|None,task:TaskDefinition,route:RoutingDecision,registration:WorkerRegistration)->None:
  checks=[
   (envelope.mission_id==head.get("mission_id"),"MISSION"),
   (envelope.human_goal_id==head.get("human_goal_id"),"HUMAN_GOAL"),
   (envelope.plan_hash==head.get("active_plan_hash"),"PLAN_HASH"),
   (envelope.runtime_revision==head.get("runtime_revision"),"RUNTIME"),
   (envelope.orchestration_version==head.get("orchestration_version"),"ORCHESTRATION"),
   (envelope.authorization_id==grant.get("authorization_id"),"AUTHORIZATION"),
   (grant.get("authority_generation")==head.get("authority_generation"),"AUTHORITY_GENERATION"),
   (continuation.get("authorization_id")==envelope.authorization_id,"CONTINUATION_AUTHORIZATION"),
   (continuation.get("continuation_id") is not None,"CONTINUATION"),
   (envelope.claim_id==continuation.get("claim_id"),"CLAIM"),
   (envelope.fencing_epoch==continuation.get("fencing_epoch")==head.get("fencing_epoch"),"FENCE"),
   (head.get("active_claim_ref") is not None,"ACTIVE_CLAIM"),
   (envelope.task_id==task.task_id,"TASK"),
   (envelope.semantic_task_key==task.semantic_task_key,"SEMANTIC_TASK"),
   (envelope.required_capability==task.required_capability,"CAPABILITY"),
   (envelope.required_capability_version==task.required_capability_version,"CAPABILITY_VERSION"),
   (envelope.input_schema==task.input_schema,"INPUT_SCHEMA"),
   (envelope.expected_output_schema==task.expected_output_schema,"OUTPUT_SCHEMA"),
   (route.task_id==task.task_id and route.selected_capability==task.required_capability,"ROUTING"),
   (route.selected_worker==registration.manifest.worker_id,"WORKER"),
   (registration.certification is not None and registration.certification.worker_build_id==registration.manifest.worker_build_id,"WORKER_BUILD"),
   (envelope.tool_call_budget<=task.tool_call_budget,"TOOL_BUDGET"),
  ]
  for ok,code in checks:
   if not ok:raise PermissionError("TASK_EXECUTION_ENVELOPE_INVALID:"+code)
