from __future__ import annotations
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Literal
from app.services.harness_git_transaction_store import canonical_bytes

DispatchKind=Literal["EXECUTE","RETRY_TRANSIENT","REPLAN","RECOVERY"]
ContinuationStatus=Literal["ISSUED","DISPATCHED","CLAIMED","CONSUMED","REVOKED","ABANDONED"]

def digest(v:Any)->str: return sha256(canonical_bytes(v)).hexdigest()
def immutable_ref(kind:str,v:Any)->tuple[str,str]:
    h=digest(v); return f"objects/{kind}/sha256/{h}.json",h

@dataclass(frozen=True)
class MissionIdentity:
    mission_id:str; human_goal_id:str; lineage_id:str
    schema:str="MissionIdentity/v1"

@dataclass(frozen=True)
class PlanRevision:
    mission_id:str; human_goal_id:str; plan_id:str; revision:int
    parent_plan_ref:str|None; parent_plan_hash:str|None; supersedes_plan_id:str|None
    reason_ref:str|None; affected_subgraph:tuple[str,...]; plan_payload:Any
    runtime_revision:str; orchestration_version:str; content_sha256:str
    schema:str="PlanRevision/v1"
    @classmethod
    def create(cls,**kw:Any)->"PlanRevision":
        logical={"schema":"PlanRevision/v1",**kw}; logical["affected_subgraph"]=list(logical.get("affected_subgraph") or ())
        h=digest(logical); logical.pop("schema"); logical["affected_subgraph"]=tuple(logical["affected_subgraph"])
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
    mission_metric_before:float|None; mission_metric_after:float|None; useful_progress:bool
    schema:str="ExecutionOutcome/v1"
    def to_dict(self)->dict[str,Any]: return asdict(self)

@dataclass(frozen=True)
class AuthorizationGrant:
    authorization_id:str; mission_id:str; human_goal_id:str; basis_state_version:int
    authority_generation:int; active_plan_ref:str; active_plan_hash:str; kind:DispatchKind
    runtime_revision:str; orchestration_version:str; reason:str
    created_from_outcome_ref:str; content_sha256:str
    schema:str="AuthorizationGrant/v1"
    @classmethod
    def create(cls,**kw:Any)->"AuthorizationGrant":
        logical={"schema":"AuthorizationGrant/v1",**kw}
        logical.pop("content_sha256",None); logical.pop("authorization_id",None)
        h=digest(logical)
        return cls(authorization_id=h,content_sha256=h,**{k:v for k,v in logical.items() if k!="schema"})

@dataclass(frozen=True)
class ContinuationRecord:
    continuation_id:str; authorization_ref:str; authorization_id:str; mission_id:str
    authority_generation:int; status:ContinuationStatus; claim_id:str|None=None
    claimant_run_id:str|None=None; fencing_epoch:int|None=None; dispatch_attempts:int=0
    dispatch_receipt:Any=None; issued_at_state_version:int|None=None
    claimed_at_state_version:int|None=None; consumed_at_state_version:int|None=None
    schema:str="ContinuationRecord/v1"
    def to_dict(self)->dict[str,Any]: return asdict(self)

@dataclass(frozen=True)
class OutboxIntent:
    continuation_id:str; authorization_ref:str; authorization_id:str; mission_id:str
    authority_generation:int; kind:DispatchKind; runtime_revision:str
    orchestration_version:str; status:str="PENDING"; schema:str="OutboxIntent/v1"

@dataclass(frozen=True)
class OperationRecord:
    operation_id:str; mission_id:str; logical_operation:str; artifact_hash:str
    claim_id:str; fencing_epoch:int; status:str; external_receipt:Any=None
    schema:str="OperationRecord/v1"

def authorize(*,current:ExecutionOutcome,previous:ExecutionOutcome|None,basis_state_version:int,
              active_plan_ref:str,active_plan_hash:str,authority_generation:int,
              kind:DispatchKind,reason:str,created_from_outcome_ref:str)->AuthorizationGrant:
    if kind=="EXECUTE" and current.transition=="REPLAN_REQUIRED":
        raise PermissionError("REPLAN_REQUIRED_FORBIDS_EXECUTE")
    same_failure=bool(previous and current.failure_signature and current.failure_signature==previous.failure_signature)
    same_strategy=bool(previous and current.strategy_signature and current.strategy_signature==previous.strategy_signature)
    if kind=="EXECUTE" and same_failure and same_strategy and not current.useful_progress:
        raise PermissionError("SAME_ROUTE_FORBIDDEN")
    return AuthorizationGrant.create(mission_id=current.mission_id,human_goal_id=current.human_goal_id,
      basis_state_version=basis_state_version,authority_generation=authority_generation,
      active_plan_ref=active_plan_ref,active_plan_hash=active_plan_hash,kind=kind,
      runtime_revision=current.runtime_revision,orchestration_version=current.orchestration_version,
      reason=reason,created_from_outcome_ref=created_from_outcome_ref)

class DurableExecutionV3:
    def __init__(self,store:Any)->None: self.store=store

    @staticmethod
    def mission_head(*,identity:MissionIdentity,active_plan_ref:str,active_plan_hash:str,
      runtime_revision:str,orchestration_version:str,state_version:int=0,fencing_epoch:int=0,
      authority_generation:int=0,mission_status:str="EXECUTE_READY")->dict[str,Any]:
        return {"schema":"HarnessMissionState/v3","mission_id":identity.mission_id,
          "human_goal_id":identity.human_goal_id,"lineage_id":identity.lineage_id,
          "state_version":state_version,"active_plan_ref":active_plan_ref,"active_plan_hash":active_plan_hash,
          "runtime_revision":runtime_revision,"orchestration_version":orchestration_version,
          "fencing_epoch":fencing_epoch,"authority_generation":authority_generation,
          "mission_status":mission_status,"active_authorization_ref":None,
          "active_continuation_ref":None,"active_claim_ref":None,"latest_outcome_ref":None,
          "latest_progress_ref":None,"active_outbox_ref":None,"pending_outbox_refs":[],"side_effect_ledger_refs":[]}

    def commit(self,*,snapshot:Any,next_head:dict[str,Any],objects:dict[str,dict[str,Any]])->str:
        prior=snapshot.mission_head; expected=None if prior is None else int(prior["state_version"])
        if prior:
            if int(next_head["state_version"])!=expected+1: raise ValueError("STATE_VERSION_DELTA_MUST_EQUAL_ONE")
            for k in ("mission_id","human_goal_id","lineage_id"):
                if next_head[k]!=prior[k]: raise ValueError("IMMUTABLE_IDENTITY_MISMATCH:"+k)
        return self.store.transact(mission_id=next_head["mission_id"],expected_head_sha=snapshot.head_sha,
          expected_state_version=expected,mission_head=next_head,immutable_objects=objects)

    def issue(self,*,snapshot:Any,current:ExecutionOutcome,previous:ExecutionOutcome|None,
              kind:DispatchKind,reason:str)->tuple[str,AuthorizationGrant,ContinuationRecord]:
        h=snapshot.mission_head
        if not h: raise PermissionError("MISSION_MISSING")
        generation=int(h.get("authority_generation",0))+1
        oref,_=immutable_ref("outcomes",current.to_dict())
        grant=authorize(current=current,previous=previous,basis_state_version=int(h["state_version"]),
          active_plan_ref=h["active_plan_ref"],
          active_plan_hash=h["active_plan_hash"],authority_generation=generation,kind=kind,
          reason=reason,created_from_outcome_ref=oref)
        gdict=asdict(grant); gref,_=immutable_ref("authorizations",gdict)
        continuation_id=digest({"mission_id":h["mission_id"],"authority_generation":generation,
          "authorization_id":grant.authorization_id})
        record=ContinuationRecord(continuation_id,gref,grant.authorization_id,h["mission_id"],
          generation,"ISSUED",issued_at_state_version=int(h["state_version"])+1)
        rdict=record.to_dict(); rref,_=immutable_ref("continuations",rdict)
        intent=asdict(OutboxIntent(continuation_id,gref,grant.authorization_id,h["mission_id"],
          generation,kind,grant.runtime_revision,grant.orchestration_version))
        iref,_=immutable_ref("outbox",intent)
        nxt={**h,"state_version":int(h["state_version"])+1,"authority_generation":generation,
          "active_authorization_ref":gref,"active_continuation_ref":rref,
          "latest_outcome_ref":oref,"active_outbox_ref":iref,
          "pending_outbox_refs":[*h.get("pending_outbox_refs",[]),iref]}
        commit=self.commit(snapshot=snapshot,next_head=nxt,objects={oref:current.to_dict(),
          gref:gdict,rref:rdict,iref:intent})
        return commit,grant,record

    def record_dispatch(self,*,snapshot:Any,continuation_id:str,dispatch_receipt:Any)->str:
        h=snapshot.mission_head; record=self._read(snapshot,h.get("active_continuation_ref") if h else None)
        if not h or not record or record.get("continuation_id")!=continuation_id:
            raise PermissionError("STALE_CONTINUATION_NOOP:NOT_CURRENT")
        if record.get("status") not in {"ISSUED","DISPATCHED"}:
            raise PermissionError("STALE_CONTINUATION_NOOP:NOT_DISPATCHABLE")
        dispatched={**record,"status":"DISPATCHED",
          "dispatch_attempts":int(record.get("dispatch_attempts",0))+1,
          "dispatch_receipt":dispatch_receipt}
        dref,_=immutable_ref("continuations",dispatched)
        active_outbox=h.get("active_outbox_ref")
        pending=[x for x in h.get("pending_outbox_refs",[]) if x!=active_outbox]
        nxt={**h,"state_version":int(h["state_version"])+1,"active_continuation_ref":dref,
             "active_outbox_ref":None,"pending_outbox_refs":pending}
        return self.commit(snapshot=snapshot,next_head=nxt,objects={dref:dispatched})

    def claim(self,*,snapshot:Any,mission_id:str,continuation_id:str,
              authorization_id:str,claimant_run_id:str)->tuple[str,str,int]:
        h=snapshot.mission_head
        if not h or h.get("mission_id")!=mission_id: raise PermissionError("STALE_CONTINUATION_NOOP:MISSION")
        rref=h.get("active_continuation_ref"); gref=h.get("active_authorization_ref")
        if not rref or not gref: raise PermissionError("NO_VALID_CANONICAL_CLAIM")
        record=self._read(snapshot,rref); grant=self._read(snapshot,gref)
        if not record or not grant: raise PermissionError("NO_VALID_CANONICAL_CLAIM")
        if record["continuation_id"]!=continuation_id or record["authorization_id"]!=authorization_id:
            raise PermissionError("CALLER_SUPPLIED_AUTHORIZATION_OBJECT_NOT_AUTHORITY")
        if grant["authorization_id"]!=authorization_id or record["authorization_ref"]!=gref:
            raise PermissionError("NO_VALID_CANONICAL_CLAIM")
        checks={"authority_generation":h["authority_generation"],"active_plan_ref":h["active_plan_ref"],
          "active_plan_hash":h["active_plan_hash"],"runtime_revision":h["runtime_revision"],
          "orchestration_version":h["orchestration_version"]}
        for k,v in checks.items():
            source=record if k=="authority_generation" else grant
            if source.get(k)!=v: raise PermissionError("STALE_CONTINUATION_NOOP:"+k)
        if record["status"] not in {"ISSUED","DISPATCHED"}:
            raise PermissionError("STALE_CONTINUATION_NOOP:NOT_CLAIMABLE")
        epoch=int(h.get("fencing_epoch",0))+1
        claim_id=digest({"continuation_id":continuation_id,"claimant_run_id":claimant_run_id,
                         "fencing_epoch":epoch})
        claimed={**record,"status":"CLAIMED","claim_id":claim_id,"claimant_run_id":claimant_run_id,
                 "fencing_epoch":epoch,"claimed_at_state_version":int(h["state_version"])+1}
        cref,_=immutable_ref("continuations",claimed)
        claim={"schema":"ClaimRecord/v1","claim_id":claim_id,"continuation_id":continuation_id,
          "claimant_run_id":claimant_run_id,"fencing_epoch":epoch}
        claimref,_=immutable_ref("claims",claim)
        nxt={**h,"state_version":int(h["state_version"])+1,"fencing_epoch":epoch,
             "active_continuation_ref":cref,"active_claim_ref":claimref}
        commit=self.commit(snapshot=snapshot,next_head=nxt,objects={cref:claimed,claimref:claim})
        return commit,claim_id,epoch

    def settle(self,*,snapshot:Any,claim_id:str,fencing_epoch:int,outcome:ExecutionOutcome,
               semantic_objects:dict[str,dict[str,Any]],next_kind:DispatchKind|None=None,
               next_reason:str="")->str:
        h=snapshot.mission_head; self.require_current_claim(snapshot=snapshot,claim_id=claim_id,fencing_epoch=fencing_epoch)
        record=self._read(snapshot,h["active_continuation_ref"])
        consumed={**record,"status":"CONSUMED","consumed_at_state_version":int(h["state_version"])+1}
        consumed_ref,_=immutable_ref("continuations",consumed)
        oref,_=immutable_ref("outcomes",outcome.to_dict())
        objects={**semantic_objects,consumed_ref:consumed,oref:outcome.to_dict()}
        nxt={**h,"state_version":int(h["state_version"])+1,"active_continuation_ref":consumed_ref,
             "latest_outcome_ref":oref,"mission_status":outcome.transition}
        if next_kind is not None:
            generation=int(h["authority_generation"])+1
            grant=authorize(current=outcome,previous=None,basis_state_version=int(h["state_version"]),
              active_plan_ref=h["active_plan_ref"],
              active_plan_hash=h["active_plan_hash"],authority_generation=generation,kind=next_kind,
              reason=next_reason,created_from_outcome_ref=oref)
            gd=asdict(grant); gr,_=immutable_ref("authorizations",gd)
            cid=digest({"mission_id":h["mission_id"],"authority_generation":generation,"authorization_id":grant.authorization_id})
            rec=ContinuationRecord(cid,gr,grant.authorization_id,h["mission_id"],generation,"ISSUED",
              issued_at_state_version=int(h["state_version"])+1)
            rd=rec.to_dict(); rr,_=immutable_ref("continuations",rd)
            intent=asdict(OutboxIntent(cid,gr,grant.authorization_id,h["mission_id"],generation,
              next_kind,grant.runtime_revision,grant.orchestration_version)); ir,_=immutable_ref("outbox",intent)
            objects.update({gr:gd,rr:rd,ir:intent}); nxt.update({"authority_generation":generation,
              "active_authorization_ref":gr,"active_continuation_ref":rr,"active_outbox_ref":ir,
              "pending_outbox_refs":[*h.get("pending_outbox_refs",[]),ir]})
        return self.commit(snapshot=snapshot,next_head=nxt,objects=objects)

    def abandon(self,*,snapshot:Any,claim_id:str,claimant_run_conclusion:str)->str:
        h=snapshot.mission_head; record=self._read(snapshot,h.get("active_continuation_ref"))
        if not record or record.get("status")!="CLAIMED" or record.get("claim_id")!=claim_id:
            raise PermissionError("NO_ACTIVE_CLAIM")
        if claimant_run_conclusion not in {"failure","cancelled","timed_out","action_required"}:
            raise PermissionError("CLAIMANT_NOT_TERMINAL")
        abandoned={**record,"status":"ABANDONED"}
        aref,_=immutable_ref("continuations",abandoned)
        nxt={**h,"state_version":int(h["state_version"])+1,"active_continuation_ref":aref,
             "active_claim_ref":None,"mission_status":"RECOVERY_REQUIRED"}
        return self.commit(snapshot=snapshot,next_head=nxt,objects={aref:abandoned})

    def require_current_claim(self,*,snapshot:Any,claim_id:str,fencing_epoch:int)->None:
        h=snapshot.mission_head
        if not h or int(h.get("fencing_epoch",-1))!=int(fencing_epoch):
            raise PermissionError("STALE_FENCING_TOKEN")
        claim=self._read(snapshot,h.get("active_claim_ref"))
        if not claim or claim.get("claim_id")!=claim_id: raise PermissionError("STALE_FENCING_TOKEN")

    def _read(self,snapshot:Any,path:str|None)->dict[str,Any]|None:
        if not path:return None
        if hasattr(snapshot,"read_json"): return snapshot.read_json(self.store,path)
        if hasattr(self.store,"read_json"): return self.store.read_json(path,snapshot.head_sha)
        if hasattr(self.store,"objects"): return self.store.objects.get(path)
        raise RuntimeError("CANONICAL_OBJECT_READ_UNAVAILABLE")
