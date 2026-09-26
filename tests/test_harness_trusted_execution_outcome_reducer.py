from dataclasses import asdict
from hashlib import sha256
import pytest
from app.services.harness_git_transaction_store import canonical_bytes
from app.services.harness_trusted_execution_outcome_reducer import ActivityExecutionEvidence,TrustedExecutionOutcomeReducer

def evidence(**changes):
 p={"schema":"ActivityExecutionEvidence/v1","mission_id":"M","continuation_id":"C","authorization_id":"A","claim_id":"CL",
 "fencing_epoch":2,"runtime_revision":"R","orchestration_version":"3.0","claimant_identity":{"run_id":"1","run_attempt":1},
 "activity_id":"x","semantic_task_key":"task","capability_id":"cap","capability_version":"1","completion_status":"FAILED",
 "typed_output_refs":[],"partial_refs":[],"raw_exception_type":"ContractError","raw_error_code":"CONTRACT_MISMATCH",
 "provider_call_count":0,"agent_call_count":0,"observed_metrics":{"mission_metric":0},"executed_operations":[],"artifact_manifest_ref":None}
 p.update(changes);p["evidence_hash"]=sha256(canonical_bytes(p)).hexdigest();return p
def canon():
 h={"mission_id":"M","human_goal_id":"H","state_version":4,"active_plan_ref":"PREF","active_plan_hash":"proof-plan","runtime_revision":"R","orchestration_version":"3.0","fencing_epoch":2}
 return h,{"plan_id":"P1","revision":1},{"mission_metric_after":0},{"authorization_id":"A"},{"continuation_id":"C","claim_id":"CL"}
def test_runtime_authority_fields_rejected():
 for field,value in [("transition","COMPLETED"),("useful_progress",True),("retry_classification","TRANSIENT"),("failure_class","PROVIDER_TRANSIENT")]:
  with pytest.raises(ValueError,match="AUTHORITY_FIELD"):ActivityExecutionEvidence.strict(evidence(**{field:value}))
def test_trusted_reducer_controls_failure_transition_and_progress():
 h,p,prev,g,c=canon();ev=ActivityExecutionEvidence.strict(evidence())
 out,d=TrustedExecutionOutcomeReducer.reduce(head=h,plan=p,previous=prev,grant=g,continuation=c,evidence=ev)
 assert out.failure_class=="CONTRACT_MISMATCH";assert out.retry_classification=="NON_RETRYABLE"
 assert out.transition=="REPLAN_REQUIRED";assert d.next_kind=="REPLAN";assert out.useful_progress is False
def test_outcome_reducer_is_byte_deterministic():
 h,p,prev,g,c=canon();ev=ActivityExecutionEvidence.strict(evidence())
 a=TrustedExecutionOutcomeReducer.reduce(head=h,plan=p,previous=prev,grant=g,continuation=c,evidence=ev)
 b=TrustedExecutionOutcomeReducer.reduce(head=h,plan=p,previous=prev,grant=g,continuation=c,evidence=ev)
 assert canonical_bytes(asdict(a[0]))==canonical_bytes(asdict(b[0]))
 assert canonical_bytes(asdict(a[1]))==canonical_bytes(asdict(b[1]))
