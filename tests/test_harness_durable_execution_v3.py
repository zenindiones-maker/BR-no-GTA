from dataclasses import dataclass
import pytest
from app.services.harness_durable_execution_v3 import (
    DurableExecutionV3, ExecutionOutcome, MissionIdentity, PlanRevision,
    dispatch_authorization,
)
from app.services.harness_git_transaction_store import CasConflict

@dataclass
class Snap:
    head_sha:str
    mission_head:dict|None

class FakeGitStore:
    def __init__(self,head):
        self.sha="H0"; self.head=head; self.commits=0
    def snapshot(self,mission_id):
        return Snap(self.sha,dict(self.head) if self.head else None)
    def transact(self,*,mission_id,expected_head_sha,expected_state_version,mission_head,immutable_objects):
        if expected_head_sha!=self.sha: raise CasConflict("CAS_CONFLICT:STALE_WORKER_NOOP")
        observed=None if self.head is None else self.head["state_version"]
        if observed!=expected_state_version: raise CasConflict("CAS_CONFLICT:STATE_VERSION")
        self.commits+=1; self.sha=f"H{self.commits}"; self.head=dict(mission_head)
        return self.sha

def plan():
    return PlanRevision.create(mission_id="M1",human_goal_id="HG1",plan_id="P1",revision=1,
      parent_plan_ref=None,parent_plan_hash=None,supersedes_plan_id=None,reason_ref=None,
      affected_subgraph=("research",),plan_payload={"tasks":["research"]},
      runtime_revision="a"*40,orchestration_version="3.0")

def outcome(**kw):
    base=dict(attempt_id="A1",mission_id="M1",human_goal_id="HG1",source_state_version=0,
      plan_id="P1",plan_revision=1,runtime_revision="a"*40,orchestration_version="3.0",
      causal_task_id="research",capability_id="gta6.research",capability_version="1",
      status="FAILED",transition="EXECUTE_READY",failure_class="PROVIDER_TRANSIENT",
      failure_code="X",failure_signature="sig1",exception_type="Timeout",
      strategy_signature="strategy1",retry_classification="TRANSIENT",provider_call_count=1,
      agent_call_count=1,executed_task_ids=("research",),reused_task_ids=(),
      new_task_result_hashes=(),replayed_task_result_hashes=(),new_artifact_hashes=(),
      new_verified_evidence=(),mission_metric_before=0,mission_metric_after=0,useful_progress=False)
    base.update(kw); return ExecutionOutcome(**base)

def runtime():
    p=plan(); identity=MissionIdentity("M1","HG1","L1")
    pref=f"objects/plans/sha256/{p.content_sha256}.json"
    head=DurableExecutionV3.mission_head(identity=identity,active_plan_ref=pref,
      active_plan_hash=p.content_sha256,runtime_revision="a"*40,orchestration_version="3.0")
    store=FakeGitStore(head)
    return DurableExecutionV3(store),store,pref,p.content_sha256

def test_identity_separates_human_goal():
    i=MissionIdentity("M1","HG1","L1")
    assert i.mission_id!="HG1" and i.human_goal_id=="HG1"

def test_plan_hash_is_recomputed():
    p=plan()
    assert len(p.content_sha256)==64
    assert p.mission_id=="M1" and p.human_goal_id=="HG1"

def test_supervisor_compares_previous_and_current():
    _,_,pref,phash=runtime()
    previous=outcome(attempt_id="A0")
    with pytest.raises(PermissionError,match="SAME_ROUTE_FORBIDDEN"):
        dispatch_authorization(current=outcome(),previous=previous,active_plan_ref=pref,
          active_plan_hash=phash,kind="EXECUTE",reason="retry")
    changed=outcome(strategy_signature="strategy2")
    auth=dispatch_authorization(current=changed,previous=previous,active_plan_ref=pref,
      active_plan_hash=phash,kind="EXECUTE",reason="new strategy")
    assert auth.kind=="EXECUTE"

def test_replan_required_hard_denies_execute():
    _,_,pref,phash=runtime()
    with pytest.raises(PermissionError,match="REPLAN_REQUIRED_FORBIDS_EXECUTE"):
        dispatch_authorization(current=outcome(transition="REPLAN_REQUIRED"),previous=None,
          active_plan_ref=pref,active_plan_hash=phash,kind="EXECUTE",reason="bad route")

def test_two_workers_same_snapshot_exactly_one_cas_wins():
    rt,store,_,_=runtime(); a=store.snapshot("M1"); b=store.snapshot("M1")
    next_head={**a.mission_head,"state_version":1,"mission_status":"RECOVERY_REQUIRED"}
    assert rt.commit(snapshot=a,next_head=next_head,objects={})=="H1"
    with pytest.raises(CasConflict,match="STALE_WORKER_NOOP"):
        rt.commit(snapshot=b,next_head=next_head,objects={})
    assert store.commits==1

def test_claim_mints_fencing_epoch_and_stale_claim_loses():
    rt,store,pref,phash=runtime()
    auth=dispatch_authorization(current=outcome(useful_progress=True,failure_signature=None,
      strategy_signature=None),previous=None,active_plan_ref=pref,active_plan_hash=phash,
      kind="EXECUTE",reason="residual work")
    a=store.snapshot("M1"); b=store.snapshot("M1")
    commit,epoch=rt.claim(snapshot=a,authorization=auth,claimant="worker-a")
    assert commit=="H1" and epoch==1 and store.head["fencing_epoch"]==1
    with pytest.raises(CasConflict,match="STALE_WORKER_NOOP"):
        rt.claim(snapshot=b,authorization=auth,claimant="worker-b")

def test_claim_validates_canonical_runtime_and_plan():
    rt,store,pref,phash=runtime()
    auth=dispatch_authorization(current=outcome(useful_progress=True,failure_signature=None,
      strategy_signature=None),previous=None,active_plan_ref=pref,active_plan_hash=phash,
      kind="EXECUTE",reason="residual")
    store.head["runtime_revision"]="b"*40
    with pytest.raises(PermissionError,match="runtime_revision"):
        rt.claim(snapshot=store.snapshot("M1"),authorization=auth,claimant="worker")

def test_fencing_revalidated_before_side_effect():
    rt,store,_,_=runtime()
    with pytest.raises(PermissionError,match="STALE_FENCING_TOKEN"):
        rt.require_current_fencing(mission_head=store.head,fencing_epoch=7)
