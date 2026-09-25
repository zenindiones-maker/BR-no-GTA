from dataclasses import dataclass
import pytest
from app.services.harness_durable_execution_v3 import (
 DurableExecutionV3,ExecutionOutcome,MissionIdentity,PlanRevision,immutable_ref)
from app.services.harness_git_transaction_store import CasConflict

@dataclass
class Snap:
 head_sha:str; mission_head:dict|None

class FakeGitStore:
 def __init__(self,head):
  self.sha="H0";self.head=head;self.objects={};self.commits=0
 def snapshot(self,mission_id): return Snap(self.sha,dict(self.head) if self.head else None)
 def read_json(self,path,ref): return self.objects.get(path)
 def transact(self,*,mission_id,expected_head_sha,expected_state_version,mission_head,immutable_objects):
  if expected_head_sha!=self.sha: raise CasConflict("CAS_CONFLICT:STALE_WORKER_NOOP")
  observed=None if self.head is None else self.head["state_version"]
  if observed!=expected_state_version: raise CasConflict("CAS_CONFLICT:STATE_VERSION")
  self.objects.update(immutable_objects);self.commits+=1;self.sha=f"H{self.commits}";self.head=dict(mission_head);return self.sha

def plan():
 return PlanRevision.create(mission_id="M1",human_goal_id="HG1",plan_id="P1",revision=1,
  parent_plan_ref=None,parent_plan_hash=None,supersedes_plan_id=None,reason_ref=None,
  affected_subgraph=("research",),plan_payload={"tasks":["research"]},runtime_revision="a"*40,
  orchestration_version="3.0")

def outcome(**kw):
 b=dict(attempt_id="A1",mission_id="M1",human_goal_id="HG1",source_state_version=0,
  plan_id="P1",plan_revision=1,runtime_revision="a"*40,orchestration_version="3.0",
  causal_task_id="research",capability_id="gta6.research",capability_version="1",status="FAILED",
  transition="EXECUTE_READY",failure_class="PROVIDER_TRANSIENT",failure_code="X",
  failure_signature="sig1",exception_type="Timeout",strategy_signature="strategy1",
  retry_classification="TRANSIENT",provider_call_count=1,agent_call_count=1,
  executed_task_ids=("research",),reused_task_ids=(),new_task_result_hashes=(),
  replayed_task_result_hashes=(),new_artifact_hashes=(),new_verified_evidence=(),
  mission_metric_before=0,mission_metric_after=0,useful_progress=True)
 b.update(kw);return ExecutionOutcome(**b)

def runtime():
 p=plan();pref=f"objects/plans/sha256/{p.content_sha256}.json"
 h=DurableExecutionV3.mission_head(identity=MissionIdentity("M1","HG1","L1"),active_plan_ref=pref,
  active_plan_hash=p.content_sha256,runtime_revision="a"*40,orchestration_version="3.0")
 s=FakeGitStore(h);s.objects[pref]=p.__dict__;return DurableExecutionV3(s),s

def issue(rt,s,**kw):
 snap=s.snapshot("M1");return rt.issue(snapshot=snap,current=outcome(**kw),previous=None,kind="EXECUTE",reason="residual")

def test_issue_is_atomic_and_refresh_claims_generation():
 rt,s=runtime();commit,g,r=issue(rt,s)
 assert commit=="H1" and s.head["state_version"]==1 and s.head["authority_generation"]==1
 assert s.head["active_authorization_ref"] in s.objects and s.head["active_continuation_ref"] in s.objects
 assert len(s.head["pending_outbox_refs"])==1
 refreshed=s.snapshot("M1")
 c,claim,fence=rt.claim(snapshot=refreshed,mission_id="M1",continuation_id=r.continuation_id,
  authorization_id=g.authorization_id,claimant_run_id="101")
 assert c=="H2" and fence==1 and claim==s.objects[s.head["active_claim_ref"]]["claim_id"]

def test_forged_or_noncanonical_authority_rejected():
 rt,s=runtime();_,g,r=issue(rt,s);snap=s.snapshot("M1")
 with pytest.raises(PermissionError,match="CALLER_SUPPLIED"):
  rt.claim(snapshot=snap,mission_id="M1",continuation_id="forged",
   authorization_id=g.authorization_id,claimant_run_id="x")
 s.head["active_authorization_ref"]="objects/authorizations/sha256/notcanonical.json"
 with pytest.raises(PermissionError,match="NO_VALID_CANONICAL_CLAIM"):
  rt.claim(snapshot=s.snapshot("M1"),mission_id="M1",continuation_id=r.continuation_id,
   authorization_id=g.authorization_id,claimant_run_id="x")

def test_two_workers_exactly_one_claims():
 rt,s=runtime();_,g,r=issue(rt,s);a=s.snapshot("M1");b=s.snapshot("M1")
 assert rt.claim(snapshot=a,mission_id="M1",continuation_id=r.continuation_id,
  authorization_id=g.authorization_id,claimant_run_id="A")[2]==1
 with pytest.raises(CasConflict,match="STALE_WORKER_NOOP"):
  rt.claim(snapshot=b,mission_id="M1",continuation_id=r.continuation_id,
   authorization_id=g.authorization_id,claimant_run_id="B")
 assert s.head["fencing_epoch"]==1

def test_old_generation_plan_runtime_orchestration_rejected():
 rt,s=runtime();_,g,r=issue(rt,s)
 for key,value in [("authority_generation",2),("active_plan_hash","bad"),
                   ("runtime_revision","b"*40),("orchestration_version","4.0")]:
  original=s.head[key];s.head[key]=value
  with pytest.raises(PermissionError,match="STALE_CONTINUATION_NOOP"):
   rt.claim(snapshot=s.snapshot("M1"),mission_id="M1",continuation_id=r.continuation_id,
    authorization_id=g.authorization_id,claimant_run_id="X")
  s.head[key]=original

def test_abandoned_claim_recovery_mints_higher_fence():
 rt,s=runtime();_,g,r=issue(rt,s);_,claim,f1=rt.claim(snapshot=s.snapshot("M1"),mission_id="M1",
  continuation_id=r.continuation_id,authorization_id=g.authorization_id,claimant_run_id="dead")
 rt.abandon(snapshot=s.snapshot("M1"),claim_id=claim,claimant_run_conclusion="failure")
 # recovery reducer issues a fresh generation
 _,g2,r2=rt.issue(snapshot=s.snapshot("M1"),current=outcome(attempt_id="A2"),previous=None,
  kind="RECOVERY",reason="abandoned claim")
 _,claim2,f2=rt.claim(snapshot=s.snapshot("M1"),mission_id="M1",continuation_id=r2.continuation_id,
  authorization_id=g2.authorization_id,claimant_run_id="new")
 assert f2>f1
 with pytest.raises(PermissionError,match="STALE_FENCING_TOKEN"):
  rt.require_current_claim(snapshot=s.snapshot("M1"),claim_id=claim,fencing_epoch=f1)
 rt.require_current_claim(snapshot=s.snapshot("M1"),claim_id=claim2,fencing_epoch=f2)

def test_settlement_all_or_nothing_and_consumes():
 rt,s=runtime();_,g,r=issue(rt,s);_,claim,f=rt.claim(snapshot=s.snapshot("M1"),mission_id="M1",
  continuation_id=r.continuation_id,authorization_id=g.authorization_id,claimant_run_id="A")
 snap=s.snapshot("M1")
 result={"schema":"TaskResultEnvelope/v2","task_id":"research","status":"COMPLETED"}
 rr,_=immutable_ref("task-results",result)
 assert rt.settle(snapshot=snap,claim_id=claim,fencing_epoch=f,outcome=outcome(status="COMPLETED",
  transition="EXECUTE_READY"),semantic_objects={rr:result},next_kind="RECOVERY",next_reason="next")=="H3"
 assert s.objects[s.head["active_continuation_ref"]]["status"]=="ISSUED"
 assert s.head["latest_outcome_ref"] in s.objects and rr in s.objects
 assert len(s.head["pending_outbox_refs"])==2

def test_settlement_cas_conflict_changes_nothing_canonical():
 rt,s=runtime();_,g,r=issue(rt,s);_,claim,f=rt.claim(snapshot=s.snapshot("M1"),mission_id="M1",
  continuation_id=r.continuation_id,authorization_id=g.authorization_id,claimant_run_id="A")
 stale=s.snapshot("M1");s.sha="OTHER"
 before=dict(s.head);objects=set(s.objects)
 with pytest.raises(CasConflict):
  rt.settle(snapshot=stale,claim_id=claim,fencing_epoch=f,outcome=outcome(),
   semantic_objects={},next_kind=None)
 assert s.head==before and set(s.objects)==objects

def test_relay_is_at_least_once_but_claim_is_single():
 rt,s=runtime();_,g,r=issue(rt,s)
 rt.record_dispatch(snapshot=s.snapshot("M1"),continuation_id=r.continuation_id,
  dispatch_receipt={"run_id":111})
 assert s.objects[s.head["active_continuation_ref"]]["status"]=="DISPATCHED"
 assert s.head["pending_outbox_refs"]==[]
 snap=s.snapshot("M1")
 _,claim,fence=rt.claim(snapshot=snap,mission_id="M1",continuation_id=r.continuation_id,
  authorization_id=g.authorization_id,claimant_run_id="111")
 assert fence==1 and claim

def test_operation_ledger_requires_current_fence():
 rt,s=runtime();_,g,r=issue(rt,s);_,claim,fence=rt.claim(snapshot=s.snapshot("M1"),
  mission_id="M1",continuation_id=r.continuation_id,authorization_id=g.authorization_id,
  claimant_run_id="A")
 _,op=rt.plan_operation(snapshot=s.snapshot("M1"),claim_id=claim,fencing_epoch=fence,
  logical_operation="youtube-private-upload",artifact_hash="abc")
 opref=s.head["side_effect_ledger_refs"][-1]
 rt.start_operation(snapshot=s.snapshot("M1"),operation_ref=opref,claim_id=claim,fencing_epoch=fence)
 started=s.head["side_effect_ledger_refs"][-1]
 rt.settle_operation(snapshot=s.snapshot("M1"),operation_ref=started,claim_id=claim,
  fencing_epoch=fence,status="UNKNOWN_RECONCILIATION_REQUIRED")
 with pytest.raises(PermissionError,match="STALE_FENCING_TOKEN"):
  rt.plan_operation(snapshot=s.snapshot("M1"),claim_id=claim,fencing_epoch=fence-1,
   logical_operation="telegram-send",artifact_hash="def")
