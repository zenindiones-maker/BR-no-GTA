from __future__ import annotations
import argparse,json,os,subprocess
from dataclasses import asdict
from pathlib import Path
from app.services.harness_durable_execution_v3 import ClaimantIdentity,DurableExecutionV3,ExecutionOutcome
from app.services.harness_git_transaction_store import GitHubGitTransactionStore

def store():
 return GitHubGitTransactionStore(repository=os.environ["GITHUB_REPOSITORY"],token=os.environ["GITHUB_TOKEN"])

def read_policy(s,snap):
 h=snap.mission_head or {}; ref=h.get("bootstrap_policy_ref")
 p=s.read_json(ref,snap.head_sha) if ref else None
 if not p or p.get("schema")!="BootstrapPolicy/v1": raise SystemExit("TRUSTED_BOOTSTRAP_MISMATCH:POLICY")
 return p

def validate_bootstrap(p):
 checks={
  "repository_id":os.environ["GITHUB_REPOSITORY_ID"],
  "workflow_path":os.environ["GITHUB_WORKFLOW_REF"].split("@",1)[0].split("/",2)[-1],
  "bootstrap_ref":os.environ["BOOTSTRAP_REF"],
  "expected_workflow_sha":os.environ["GITHUB_WORKFLOW_SHA"],
  "allowed_event":"workflow_dispatch"}
 for k,v in checks.items():
  if str(p.get(k))!=str(v): raise SystemExit("TRUSTED_BOOTSTRAP_MISMATCH:"+k)
 print("BOOTSTRAP_PROVENANCE=PASS")

def claim(a):
 s=store(); snap=s.snapshot(a.mission_id); p=read_policy(s,snap);validate_bootstrap(p)
 ident=ClaimantIdentity(os.environ["GITHUB_RUN_ID"],int(os.environ["GITHUB_RUN_ATTEMPT"]),
  os.environ["GITHUB_WORKFLOW_REF"],os.environ["GITHUB_WORKFLOW_SHA"],"trusted_claim")
 rt=DurableExecutionV3(s)
 commit,cid,fence=rt.claim(snapshot=snap,mission_id=a.mission_id,continuation_id=a.continuation_id,
  authorization_id=a.authorization_id,claimant_identity=ident)
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
 payload=json.loads(os.environ["EXECUTION_RESULT_JSON"])
 s=store();snap=s.snapshot(a.mission_id);p=read_policy(s,snap);validate_bootstrap(p)
 ident=ClaimantIdentity(**payload["claimant_identity"])
 rt=DurableExecutionV3(s)
 rt.require_current_claim(snapshot=snap,claim_id=payload["claim_id"],fencing_epoch=int(payload["fencing_epoch"]),
  claimant_identity=ident)
 if payload["runtime_revision"]!=snap.mission_head["runtime_revision"]: raise SystemExit("RUNTIME_REVISION_MISMATCH")
 if payload["orchestration_version"]!=snap.mission_head["orchestration_version"]: raise SystemExit("VERSION_INCOMPATIBLE")
 outcome=ExecutionOutcome(**payload["proposed_outcome"])
 rt.settle(snapshot=snap,claim_id=payload["claim_id"],fencing_epoch=int(payload["fencing_epoch"]),
  outcome=outcome,semantic_objects={})
 print("TRUSTED_SETTLEMENT=PASS")
 print("SETTLED_ATTEMPT_HAS_NO_ACTIVE_CLAIM=PASS")

def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["claim","settle"]);p.add_argument("--mission-id",required=True)
 p.add_argument("--continuation-id",required=True);p.add_argument("--authorization-id",required=True);a=p.parse_args()
 claim(a) if a.mode=="claim" else settle(a)
if __name__=="__main__":main()
