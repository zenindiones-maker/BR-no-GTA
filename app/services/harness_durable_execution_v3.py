from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Literal
from app.services.harness_git_transaction_store import canonical_bytes

DispatchKind = Literal["EXECUTE","RETRY_TRANSIENT","REPLAN","RECOVERY"]
LedgerStatus = Literal["ISSUED","CLAIMED","CONSUMED","REVOKED"]

def _digest(v: Any)->str: return sha256(canonical_bytes(v)).hexdigest()
def immutable_ref(kind:str,v:Any)->tuple[str,str]:
    h=_digest(v); return f"objects/{kind}/sha256/{h}.json",h

@dataclass(frozen=True)
class MissionIdentity:
    mission_id:str; human_goal_id:str; lineage_id:str
    schema:str="MissionIdentity/v1"

@dataclass(frozen=True)
class PlanRevision:
    mission_id:str; human_goal_id:str; plan_id:str; revision:int
    parent_plan_ref:str|None; parent_plan_hash:str|None
    supersedes_plan_id:str|None; reason_ref:str|None
    affected_subgraph:tuple[str,...]; plan_payload:Any
    runtime_revision:str; orchestration_version:str; content_sha256:str
    schema:str="PlanRevision/v1"
    @classmethod
    def create(cls,**kw:Any)->"PlanRevision":
        logical={"schema":"PlanRevision/v1",**kw}
        logical["affected_subgraph"]=list(logical.get("affected_subgraph") or ())
        h=_digest(logical); logical.pop("schema")
        logical["affected_subgraph"]=tuple(logical["affected_subgraph"])
        return cls(**logical,content_sha256=h)

@dataclass(frozen=True)
class ExecutionOutcome:
    attempt_id:str; mission_id:str; human_goal_id:str; source_state_version:int
    plan_id:str; plan_revision:int; runtime_revision:str; orchestration_version:str
    causal_task_id:str|None; capability_id:str|None; capability_version:str|None
    status:str; transition:str; failure_class:str|None; failure_code:str|None
    failure_signature:str|None; exception_type:str|None; strategy_signature:str|None
    retry_classification:str|None; provider_call_count:int; agent_call_count:int
    executed_task_ids:tuple[str,...]; reused_task_ids:tuple[str,...]
    new_task_result_hashes:tuple[str,...]; replayed_task_result_hashes:tuple[str,...]
    new_artifact_hashes:tuple[str,...]; new_verified_evidence:tuple[str,...]
    mission_metric_before:float|None; mission_metric_after:float|None
    useful_progress:bool; schema:str="ExecutionOutcome/v1"
    def to_dict(self)->dict[str,Any]: return asdict(self)

@dataclass(frozen=True)
class DispatchAuthorization:
    authorization_id:str; mission_id:str; source_state_version:int
    active_plan_ref:str; active_plan_hash:str; kind:DispatchKind
    runtime_revision:str; orchestration_version:str; reason:str
    status:LedgerStatus="ISSUED"; claimant:str|None=None; fencing_epoch:int|None=None
    schema:str="DispatchAuthorization/v1"
    def to_dict(self)->dict[str,Any]: return asdict(self)

@dataclass(frozen=True)
class OutboxIntent:
    continuation_id:str; authorization_ref:str; authorization_id:str
    mission_id:str; kind:DispatchKind; runtime_revision:str; orchestration_version:str
    status:str="PENDING"; schema:str="OutboxIntent/v1"

def dispatch_authorization(*,current:ExecutionOutcome,previous:ExecutionOutcome|None,
                           active_plan_ref:str,active_plan_hash:str,
                           kind:DispatchKind,reason:str)->DispatchAuthorization:
    if kind=="EXECUTE" and current.transition=="REPLAN_REQUIRED":
        raise PermissionError("REPLAN_REQUIRED_FORBIDS_EXECUTE")
    same_failure=bool(previous and current.failure_signature and
                      current.failure_signature==previous.failure_signature)
    same_strategy=bool(previous and current.strategy_signature and
                       current.strategy_signature==previous.strategy_signature)
    if kind=="EXECUTE" and same_failure and same_strategy and not current.useful_progress:
        raise PermissionError("SAME_ROUTE_FORBIDDEN")
    seed={"mission_id":current.mission_id,"source_state_version":current.source_state_version,
          "active_plan_ref":active_plan_ref,"active_plan_hash":active_plan_hash,"kind":kind,
          "runtime_revision":current.runtime_revision,
          "orchestration_version":current.orchestration_version,"reason":reason}
    return DispatchAuthorization(_digest(seed),current.mission_id,current.source_state_version,
        active_plan_ref,active_plan_hash,kind,current.runtime_revision,
        current.orchestration_version,reason)

class DurableExecutionV3:
    """Deterministic reducer over an injected distributed Git CAS store."""
    @staticmethod
    def mission_head(*,identity:MissionIdentity,active_plan_ref:str,active_plan_hash:str,
                     runtime_revision:str,orchestration_version:str,state_version:int=0,
                     fencing_epoch:int=0,mission_status:str="EXECUTE_READY",
                     latest_outcome_ref:str|None=None,pending_outbox_refs:tuple[str,...]=())->dict[str,Any]:
        return {"schema":"HarnessMissionState/v3","mission_id":identity.mission_id,
          "human_goal_id":identity.human_goal_id,"lineage_id":identity.lineage_id,
          "state_version":state_version,"active_plan_ref":active_plan_ref,
          "active_plan_hash":active_plan_hash,"runtime_revision":runtime_revision,
          "orchestration_version":orchestration_version,"fencing_epoch":fencing_epoch,
          "mission_status":mission_status,"latest_outcome_ref":latest_outcome_ref,
          "latest_progress_ref":None,"pending_outbox_refs":list(pending_outbox_refs),
          "side_effect_ledger_refs":[]}

    def __init__(self,store:Any)->None: self.store=store

    def commit(self,*,snapshot:Any,next_head:dict[str,Any],
               objects:dict[str,dict[str,Any]])->str:
        prior=snapshot.mission_head
        expected=None if prior is None else int(prior["state_version"])
        if prior:
            if int(next_head["state_version"])!=expected+1:
                raise ValueError("STATE_VERSION_DELTA_MUST_EQUAL_ONE")
            for k in ("mission_id","human_goal_id","lineage_id"):
                if next_head[k]!=prior[k]: raise ValueError("IMMUTABLE_IDENTITY_MISMATCH:"+k)
        return self.store.transact(mission_id=next_head["mission_id"],
          expected_head_sha=snapshot.head_sha,expected_state_version=expected,
          mission_head=next_head,immutable_objects=objects)

    def issue(self,*,snapshot:Any,authorization:DispatchAuthorization)->str:
        head=snapshot.mission_head
        if not head: raise PermissionError("MISSION_MISSING")
        self._validate_authorization(head,authorization)
        auth=authorization.to_dict()
        aref,_=immutable_ref("authorizations",auth)
        intent=asdict(OutboxIntent(authorization.authorization_id,aref,
          authorization.authorization_id,authorization.mission_id,authorization.kind,
          authorization.runtime_revision,authorization.orchestration_version))
        iref,_=immutable_ref("outbox",intent)
        nxt={**head,"state_version":int(head["state_version"])+1,
             "pending_outbox_refs":[*head.get("pending_outbox_refs",[]),iref]}
        return self.commit(snapshot=snapshot,next_head=nxt,objects={aref:auth,iref:intent})

    def claim(self,*,snapshot:Any,authorization:DispatchAuthorization,claimant:str)->tuple[str,int]:
        head=snapshot.mission_head
        if not head: raise PermissionError("STALE_CONTINUATION_NOOP:MISSION_MISSING")
        self._validate_authorization(head,authorization)
        if authorization.status!="ISSUED":
            raise PermissionError("STALE_CONTINUATION_NOOP:NOT_ISSUED")
        epoch=int(head.get("fencing_epoch",0))+1
        claimed={**authorization.to_dict(),"status":"CLAIMED","claimant":claimant,
                 "fencing_epoch":epoch}
        cref,_=immutable_ref("authorizations",claimed)
        nxt={**head,"state_version":int(head["state_version"])+1,"fencing_epoch":epoch}
        commit=self.commit(snapshot=snapshot,next_head=nxt,objects={cref:claimed})
        return commit,epoch

    @staticmethod
    def _validate_authorization(head:dict[str,Any],a:DispatchAuthorization)->None:
        checks={"mission_id":a.mission_id,"state_version":a.source_state_version,
          "active_plan_ref":a.active_plan_ref,"active_plan_hash":a.active_plan_hash,
          "runtime_revision":a.runtime_revision,"orchestration_version":a.orchestration_version}
        for k,v in checks.items():
            if head.get(k)!=v: raise PermissionError("STALE_CONTINUATION_NOOP:"+k)

    @staticmethod
    def require_current_fencing(*,mission_head:dict[str,Any],fencing_epoch:int)->None:
        if int(mission_head.get("fencing_epoch",-1))!=int(fencing_epoch):
            raise PermissionError("STALE_FENCING_TOKEN")
