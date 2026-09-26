from __future__ import annotations
from dataclasses import dataclass,asdict
from hashlib import sha256
from typing import Any
from app.services.harness_git_transaction_store import canonical_bytes
from app.services.harness_durable_execution_v3 import ExecutionOutcome
from app.services.harness_trusted_plan_binding import ValidatedPlanBinding

FORBIDDEN={"mission_status","next_transition","transition","next_kind","failure_class","retry_classification",
"useful_progress","authority_generation","next_authorization","next_continuation","next_outbox","mission_metric_after",
"strategy_signature","failure_signature","executed_task_ids","new_task_result_hashes","new_artifact_hashes"}

@dataclass(frozen=True)
class ActivityExecutionEvidence:
 mission_id:str;continuation_id:str;authorization_id:str;claim_id:str;fencing_epoch:int
 runtime_revision:str;orchestration_version:str;claimant_identity:dict[str,Any]
 activity_id:str;semantic_task_key:str;capability_id:str;capability_version:str
 completion_status:str;typed_output_refs:tuple[str,...];partial_refs:tuple[str,...]
 raw_exception_type:str|None;raw_error_code:str|None;provider_call_count:int;agent_call_count:int
 observed_metrics:dict[str,float];executed_operations:tuple[str,...];artifact_manifest_ref:str|None
 evidence_hash:str;schema:str="ActivityExecutionEvidence/v1"
 @classmethod
 def strict(cls,p:dict[str,Any])->"ActivityExecutionEvidence":
  if set(p)&FORBIDDEN: raise ValueError("RESULT_EVIDENCE_INVALID:AUTHORITY_FIELD")
  if p.get("schema")!="ActivityExecutionEvidence/v1": raise ValueError("RESULT_EVIDENCE_INVALID:SCHEMA")
  if len(canonical_bytes(p))>262144: raise ValueError("RESULT_EVIDENCE_INVALID:SIZE")
  raw={k:v for k,v in p.items() if k!="evidence_hash"}
  if sha256(canonical_bytes(raw)).hexdigest()!=p.get("evidence_hash"): raise ValueError("RESULT_EVIDENCE_INVALID:HASH")
  for k in ("typed_output_refs","partial_refs","executed_operations"): p[k]=tuple(p.get(k) or ())
  return cls(**p)

@dataclass(frozen=True)
class TransitionDecision:
 transition:str;next_kind:str|None;useful_progress:bool;reason:str
 schema:str="TransitionDecision/v1"

class TrustedExecutionOutcomeReducer:
 @staticmethod
 def reduce(*,head:dict[str,Any],validated_plan:ValidatedPlanBinding,previous:dict[str,Any]|None,
            grant:dict[str,Any],continuation:dict[str,Any],evidence:ActivityExecutionEvidence)->tuple[ExecutionOutcome,TransitionDecision]:
  if evidence.mission_id!=head["mission_id"] or evidence.authorization_id!=grant["authorization_id"]: raise ValueError("RESULT_EVIDENCE_INVALID:IDENTITY")
  if evidence.continuation_id!=continuation["continuation_id"] or evidence.claim_id!=continuation["claim_id"]: raise ValueError("RESULT_EVIDENCE_INVALID:CLAIM")
  if evidence.fencing_epoch!=head["fencing_epoch"] or evidence.runtime_revision!=head["runtime_revision"]: raise ValueError("RESULT_EVIDENCE_INVALID:FENCE_RUNTIME")
  if evidence.orchestration_version!=head["orchestration_version"]: raise ValueError("RESULT_EVIDENCE_INVALID:ORCHESTRATION")
  ok=evidence.completion_status=="COMPLETED" and not evidence.raw_exception_type and not evidence.raw_error_code
  failure_class=None if ok else ("CONTRACT_MISMATCH" if evidence.raw_error_code and ("CONTRACT" in evidence.raw_error_code or "PRECONDITION" in evidence.raw_error_code) else "DETERMINISTIC_LOGIC_FAILURE")
  retry=None if ok else "NON_RETRYABLE"
  before=float((previous or {}).get("mission_metric_after") or 0)
  after=float(evidence.observed_metrics.get("mission_metric",before))
  useful=bool(evidence.typed_output_refs or evidence.partial_refs or after>before)
  transition="COMPLETED" if ok else ("REPLAN_REQUIRED" if failure_class=="CONTRACT_MISMATCH" else "RECOVERY_REQUIRED")
  next_kind=None if ok else ("REPLAN" if transition=="REPLAN_REQUIRED" else "RECOVERY")
  failure_code=evidence.raw_error_code
  fs=None if ok else sha256(canonical_bytes({"exception":evidence.raw_exception_type,"code":failure_code,"task":evidence.semantic_task_key})).hexdigest()
  strategy=sha256(canonical_bytes({"plan":validated_plan.plan_ref,"task":evidence.semantic_task_key,"capability":evidence.capability_id})).hexdigest()
  out=ExecutionOutcome(attempt_id=evidence.activity_id,mission_id=head["mission_id"],human_goal_id=head["human_goal_id"],
   source_state_version=int(head["state_version"]),plan_id=validated_plan.plan_id,plan_revision=validated_plan.revision,
   runtime_revision=head["runtime_revision"],orchestration_version=head["orchestration_version"],causal_task_id=evidence.semantic_task_key,
   capability_id=evidence.capability_id,capability_version=evidence.capability_version,status="COMPLETED" if ok else "FAILED",
   transition=transition,failure_class=failure_class,failure_code=failure_code,failure_signature=fs,exception_type=evidence.raw_exception_type,
   strategy_signature=strategy,retry_classification=retry,provider_call_count=evidence.provider_call_count,agent_call_count=evidence.agent_call_count,
   executed_task_ids=(evidence.semantic_task_key,),reused_task_ids=(),new_task_result_hashes=tuple(evidence.typed_output_refs),
   replayed_task_result_hashes=(),new_artifact_hashes=tuple(evidence.partial_refs),new_verified_evidence=(evidence.evidence_hash,),
   mission_metric_before=before,mission_metric_after=after,useful_progress=useful)
  return out,TransitionDecision(transition,next_kind,useful,"trusted deterministic reduction")
