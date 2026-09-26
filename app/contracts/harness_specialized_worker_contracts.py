from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
from app.services.harness_git_transaction_store import canonical_bytes
from typing import Any

@dataclass(frozen=True)
class TaskExecutionEnvelope:
 mission_id:str;human_goal_id:str;lineage_id:str;plan_id:str;plan_revision:int;plan_hash:str
 task_id:str;semantic_task_key:str;attempt_id:str;required_capability:str;required_capability_version:str
 input_refs:tuple[str,...];input_schema:str;expected_output_schema:str;dependency_result_refs:tuple[str,...]
 runtime_revision:str;orchestration_version:str;authorization_id:str;claim_id:str;fencing_epoch:int
 execution_budget:dict[str,Any];tool_call_budget:int;timeout_policy:dict[str,Any];review_requirement:str|None;trace_id:str
 schema:str="TaskExecutionEnvelope/v1"

@dataclass(frozen=True)
class TaskExecutionEvidence:
 mission_id:str;plan_id:str;plan_revision:int;task_id:str;attempt_id:str;capability_id:str;capability_version:str
 worker_id:str;worker_build_id:str;completion_status:str;typed_output_refs:tuple[str,...];partial_refs:tuple[str,...];provider_id:str|None;model_id:str|None
 provider_call_count:int;agent_call_count:int;executed_operations:tuple[str,...];raw_exception_type:str|None;raw_error_code:str|None
 observed_metrics:dict[str,float];checkpoint_refs:tuple[str,...];evidence_hash:str;schema:str="TaskExecutionEvidence/v1"

@dataclass(frozen=True)
class ReviewEvidence:
 reviewed_task_result_ref:str;reviewer_capability:str;reviewer_identity:str;schema_validation:str
 findings:tuple[str,...];violations:tuple[str,...];recommendation:str;evidence_refs:tuple[str,...];schema:str="ReviewEvidence/v1"

@dataclass(frozen=True)
class FailureEpisode:
 mission_id:str;plan_id:str;plan_revision:int;task_id:str;attempt_id:str;capability:str;provider:str|None;model:str|None
 latency_ms:int;timeout_budget_ms:int;failure_class:str;failure_code:str|None;failure_signature:str;strategy_signature:str
 claim_id:str;fencing_epoch:int;runtime_revision:str;orchestration_version:str;recovery_decision:str;schema:str="FailureEpisode/v1"

@dataclass(frozen=True)
class RoutingDecision:
 candidate_set:tuple[str,...];rejections:dict[str,str];selected_capability_provider:str;model:str|None;reason:str;policy_version:str
 schema:str="RoutingDecision/v1"

@dataclass(frozen=True)
class PolicyDecision:
 decision_id:str;policy_id:str;policy_version:str;decision_type:str;input_refs:tuple[str,...];input_hash:str;decision:str;reason:str
 mission_id:str;plan_id:str;plan_revision:int;created_from_state_version:int;task_id:str|None=None;schema:str="PolicyDecision/v1"

AUTHORITY_RULE="LLM_PROPOSES_TRUSTED_STATE_MACHINE_DISPOSES"

FORBIDDEN_WORKER_AUTHORITY_FIELDS=frozenset({"mission_status","transition","next_transition","next_kind","failure_class","retry_classification","useful_progress","authority_generation","next_authorization","next_continuation","next_outbox","selected_next_worker","selected_next_agent","terminality"})

def validate_worker_evidence_payload(payload:dict)->None:
 extra=set(payload)-{f.name for f in __import__("dataclasses").fields(TaskExecutionEvidence)}
 forbidden=FORBIDDEN_WORKER_AUTHORITY_FIELDS & set(payload)
 if forbidden: raise ValueError("WORKER_EVIDENCE_INVALID:AUTHORITY_FIELD")
 if extra: raise ValueError("WORKER_EVIDENCE_INVALID:UNKNOWN_FIELD")
 supplied=str(payload.get("evidence_hash") or "")
 raw={k:v for k,v in payload.items() if k!="evidence_hash"}
 if supplied!=sha256(canonical_bytes(raw)).hexdigest(): raise ValueError("WORKER_EVIDENCE_INVALID:HASH")
