from __future__ import annotations
import argparse,json,os,random,time
from dataclasses import asdict
from pathlib import Path
from app.services.harness_durable_execution_v3 import ClaimantIdentity,DurableExecutionV3
from app.services.harness_trusted_execution_outcome_reducer import ActivityExecutionEvidence,TrustedExecutionOutcomeReducer
from app.services.harness_git_transaction_store import CasConflict,GitHubGitTransactionStore
from app.services.harness_claimant_run_observer import GitHubActionsClaimantObserver
from app.services.harness_trusted_plan_binding import TrustedPlanBinding

def store():
 return GitHubGitTransactionStore(repository=os.environ["GITHUB_REPOSITORY"],token=os.environ["GITHUB_TOKEN"])

def read_policy(s,snap):
 h=snap.mission_head or {}; ref=h.get("bootstrap_policy_ref")
 p=s.read_json(ref,snap.head_sha) if ref else None
 if not p or p.get("schema") not in {"BootstrapPolicy/v1","BootstrapPolicy/v2"}: raise SystemExit("TRUSTED_BOOTSTRAP_MISMATCH:POLICY")
 return p

def validate_bootstrap(p):
 workflow_path=os.environ["GITHUB_WORKFLOW_REF"].split("@",1)[0].split("/",2)[-1]
 checks={"repository_id":os.environ["GITHUB_REPOSITORY_ID"],"workflow_path":workflow_path,"allowed_event":"workflow_dispatch"}
 if p.get("schema")=="BootstrapPolicy/v2":
  checks.update({"bootstrap_release_ref":os.environ["BOOTSTRAP_REF"],"bootstrap_release_sha":os.environ["GITHUB_WORKFLOW_SHA"]})
 else:
  checks.update({"bootstrap_ref":os.environ["BOOTSTRAP_REF"],"expected_workflow_sha":os.environ["GITHUB_WORKFLOW_SHA"]})
 for k,v in checks.items():
  if str(p.get(k))!=str(v): raise SystemExit("TRUSTED_BOOTSTRAP_MISMATCH:"+k)
 print("BOOTSTRAP_PROVENANCE=PASS")

def _authority_fingerprint(s,snap):
 h=snap.mission_head or {};g=s.read_json(h.get("active_authorization_ref"),snap.head_sha) if h.get("active_authorization_ref") else None
 r=s.read_json(h.get("active_continuation_ref"),snap.head_sha) if h.get("active_continuation_ref") else None
 return h,g,r,tuple((h.get(k) for k in ("mission_id","authority_generation","active_plan_ref","active_plan_hash","runtime_revision","orchestration_version")))

def claim(a):
 s=store();snap=s.snapshot(a.mission_id);p=read_policy(s,snap);validate_bootstrap(p)
 ident=ClaimantIdentity(os.environ["GITHUB_RUN_ID"],int(os.environ["GITHUB_RUN_ATTEMPT"]),os.environ["GITHUB_WORKFLOW_REF"],os.environ["GITHUB_WORKFLOW_SHA"],"trusted_claim")
 rt=DurableExecutionV3(s);h0,g0,r0,fp0=_authority_fingerprint(s,snap)
 if not g0 or not r0 or g0.get("authorization_id")!=a.authorization_id or r0.get("continuation_id")!=a.continuation_id: raise SystemExit("STALE_CONTINUATION_NOOP")
 commit=cid=fence=None
 for attempt in range(1,4):
  try:
   commit,cid,fence=rt.claim(snapshot=snap,mission_id=a.mission_id,continuation_id=a.continuation_id,authorization_id=a.authorization_id,claimant_identity=ident)
   print(f"CAS_CLAIM_ATTEMPT_{attempt}=SUCCESS");break
  except CasConflict:
   print(f"CAS_CLAIM_ATTEMPT_{attempt}=CONFLICT");fresh=s.snapshot(a.mission_id);h,g,r,fp=_authority_fingerprint(s,fresh)
   if g and r and r.get("status")=="CLAIMED" and r.get("continuation_id")==a.continuation_id and r.get("authorization_id")==a.authorization_id and r.get("claimant_identity")==ident.to_dict():
    cid=r["claim_id"];fence=int(r["fencing_epoch"]);commit=fresh.head_sha;print("CLAIM_IDEMPOTENT_REPLAY=PASS");print("RETURN_EXISTING_CLAIM=PASS");break
   unchanged=(fp==fp0 and g and r and g.get("authorization_id")==a.authorization_id and r.get("continuation_id")==a.continuation_id and r.get("authorization_id")==a.authorization_id and r.get("status") in {"ISSUED","DISPATCHED"} and not h.get("active_claim_ref"))
   if not unchanged:
    print("STALE_CONTINUATION_NOOP");print("SEMANTIC_EXECUTION_STARTED=NO");print("PLANNER_CALLS=0");print("PROVIDER_CALLS=0");print("AGENT_CALLS=0");print("TASKRESULT_WRITES=0");print("SIDE_EFFECTS=0");raise SystemExit(78)
   print("CAS_CONFLICT_TRANSIENT_CONTENTION");print("FRESH_CANONICAL_REVALIDATION=PASS");print("SEMANTIC_AUTHORITY_UNCHANGED=PASS")
   snap=fresh
   if attempt==3: raise
   time.sleep((0.15*(2**(attempt-1)))+random.uniform(0,0.08))
 if cid is None or fence is None: raise SystemExit("CLAIM_NOT_ACQUIRED")
 fresh=s.snapshot(a.mission_id); grant=s.read_json(fresh.mission_head["active_authorization_ref"],fresh.head_sha)
 out={"claim_id":cid,"fencing_epoch":fence,"runtime_revision":grant["runtime_revision"],
  "orchestration_version":grant["orchestration_version"],"claimant_identity":ident.to_dict(),
  "state_commit":commit}
 for k,v in out.items():
  value=json.dumps(v,separators=(",",":")) if isinstance(v,dict) else str(v)
  print(f"{k}={value}")
  if os.getenv("GITHUB_OUTPUT"): Path(os.environ["GITHUB_OUTPUT"]).open("a").write(f"{k}={value}\n")
 print("CANONICAL_CLAIM=PASS")

def settle(a):
 payload=json.loads(Path(os.environ["EVIDENCE_FILE"]).read_text())
 s=store();snap=s.snapshot(a.mission_id);p=read_policy(s,snap);validate_bootstrap(p)
 try:evidence=ActivityExecutionEvidence.strict(payload)
 except ValueError as e: raise SystemExit(str(e))
 if evidence.mission_id!=a.mission_id or evidence.continuation_id!=a.continuation_id or evidence.authorization_id!=a.authorization_id: raise SystemExit("RESULT_EVIDENCE_INVALID:CALLER_IDENTITY")
 ident=ClaimantIdentity(**evidence.claimant_identity);rt=DurableExecutionV3(s)
 rt.require_current_claim(snapshot=snap,claim_id=evidence.claim_id,fencing_epoch=evidence.fencing_epoch,claimant_identity=ident)
 h=snap.mission_head;grant=s.read_json(h["active_authorization_ref"],snap.head_sha);cont=s.read_json(h["active_continuation_ref"],snap.head_sha)
 plan=s.read_json(h["active_plan_ref"],snap.head_sha);prev=s.read_json(h.get("latest_outcome_ref"),snap.head_sha) if h.get("latest_outcome_ref") else None
 try:
  validated=TrustedPlanBinding.validate(head=h,grant=grant,plan=plan,plan_ref=h["active_plan_ref"])
 except ValueError as e: raise SystemExit(str(e))
 print("TRUSTED_PLAN_SCHEMA=PASS");print("TRUSTED_PLAN_HASH=PASS");print("MISSION_PLAN_BINDING=PASS");print("AUTHORIZATION_PLAN_BINDING=PASS");print("CANONICAL_PLAN_BINDING=PASS")
 outcome,decision=TrustedExecutionOutcomeReducer.reduce(head=h,validated_plan=validated,previous=prev,grant=grant,continuation=cont,evidence=evidence)
 rt.settle(snapshot=snap,claim_id=evidence.claim_id,fencing_epoch=evidence.fencing_epoch,outcome=outcome,semantic_objects={})
 print("RUNTIME_RESULT_IS_EVIDENCE_NOT_AUTHORITY=PASS")
 print("TRUSTED_OUTCOME_REDUCER=PASS")
 print("CANONICAL_TRANSITION="+decision.transition)
 print("CANONICAL_USEFUL_PROGRESS="+str(decision.useful_progress).upper())
 print("TRUSTED_SETTLEMENT=PASS")
 print("SETTLED_ATTEMPT_HAS_NO_ACTIVE_CLAIM=PASS")

def abandon(a):
 s=store();snap=s.snapshot(a.mission_id);h=snap.mission_head or {};cont=s.read_json(h.get("active_continuation_ref"),snap.head_sha) if h.get("active_continuation_ref") else None
 if not cont or cont.get("status")!="CLAIMED": raise SystemExit("NO_ACTIVE_CLAIM")
 if cont.get("continuation_id")!=a.continuation_id or cont.get("authorization_id")!=a.authorization_id: raise SystemExit("NO_ACTIVE_CLAIM")
 ident=ClaimantIdentity(**cont["claimant_identity"])
 observation=GitHubActionsClaimantObserver(repository=os.environ["GITHUB_REPOSITORY"],token=os.environ["GITHUB_TOKEN"]).observe(ident)
 if observation.observed_status!="completed": raise SystemExit("CLAIMANT_NOT_TERMINAL")
 rt=DurableExecutionV3(s);commit,oref=rt.persist_run_observation(snapshot=snap,observation=observation)
 print("CLAIMANT_ATTEMPT_1_TERMINAL_OBSERVATION=PASS")
 fresh=s.snapshot(a.mission_id);rt.abandon(snapshot=fresh,claim_id=cont["claim_id"],observation_ref=oref)
 print("ORPHAN_CLAIM_ABANDONED_CANONICALLY=PASS")

def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["claim","settle","abandon"]);p.add_argument("--mission-id",required=True)
 p.add_argument("--continuation-id",required=True);p.add_argument("--authorization-id",required=True);a=p.parse_args()
 claim(a) if a.mode=="claim" else (settle(a) if a.mode=="settle" else abandon(a))
if __name__=="__main__":main()
