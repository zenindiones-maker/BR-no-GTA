from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from app.services.harness_git_transaction_store import canonical_bytes

REQUIRED=("schema","mission_id","human_goal_id","plan_id","revision","parent_plan_ref","parent_plan_hash","supersedes_plan_id","reason_ref","affected_subgraph","plan_payload","runtime_revision","orchestration_version","content_sha256")

@dataclass(frozen=True)
class ValidatedPlanBinding:
 plan_id:str
 revision:int
 plan_ref:str
 plan_hash:str
 runtime_revision:str
 orchestration_version:str
 schema:str="ValidatedPlanBinding/v1"

class TrustedPlanBinding:
 @staticmethod
 def validate(*,head:dict[str,Any],grant:dict[str,Any],plan:dict[str,Any],plan_ref:str)->ValidatedPlanBinding:
  if plan.get("schema")!="PlanRevision/v1" or any(k not in plan for k in REQUIRED):
   raise ValueError("RESULT_EVIDENCE_INVALID:PLAN_SCHEMA")
  raw={k:v for k,v in plan.items() if k!="content_sha256"}
  recomputed=sha256(canonical_bytes(raw)).hexdigest()
  if recomputed!=plan["content_sha256"]: raise ValueError("RESULT_EVIDENCE_INVALID:PLAN_HASH")
  expected_ref=f"objects/plans/sha256/{recomputed}.json"
  if plan_ref!=expected_ref or head.get("active_plan_ref")!=plan_ref or head.get("active_plan_hash")!=recomputed:
   raise ValueError("RESULT_EVIDENCE_INVALID:PLAN_BINDING")
  for k in ("mission_id","human_goal_id","runtime_revision","orchestration_version"):
   if plan.get(k)!=head.get(k): raise ValueError("RESULT_EVIDENCE_INVALID:PLAN_BINDING")
  for k in ("active_plan_ref","active_plan_hash","runtime_revision","orchestration_version","mission_id","human_goal_id","authority_generation"):
   if grant.get(k)!=head.get(k): raise ValueError("RESULT_EVIDENCE_INVALID:AUTHORITY_PLAN_BINDING")
  return ValidatedPlanBinding(str(plan["plan_id"]),int(plan["revision"]),plan_ref,recomputed,str(plan["runtime_revision"]),str(plan["orchestration_version"]))
