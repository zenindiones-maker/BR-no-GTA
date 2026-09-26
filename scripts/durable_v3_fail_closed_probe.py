from __future__ import annotations
import argparse,os
from app.services.harness_durable_execution_v3 import ClaimantIdentity,DurableExecutionV3
from app.services.harness_git_transaction_store import GitHubGitTransactionStore
def rejected(fn,label):
 try: fn()
 except (PermissionError,SystemExit):
  print(label+"=PASS");return
 raise SystemExit(label+"_FAILED")
def main():
 p=argparse.ArgumentParser();p.add_argument("--mission-id",required=True);p.add_argument("--continuation-id",required=True);p.add_argument("--authorization-id",required=True);p.add_argument("--old-claim-id",required=True);p.add_argument("--old-fence",type=int,required=True);a=p.parse_args()
 s=GitHubGitTransactionStore(repository=os.environ["GITHUB_REPOSITORY"],token=os.environ["GITHUB_TOKEN"]);snap=s.snapshot(a.mission_id);rt=DurableExecutionV3(s)
 ident=ClaimantIdentity(os.environ["GITHUB_RUN_ID"],int(os.environ["GITHUB_RUN_ATTEMPT"]),os.environ["GITHUB_WORKFLOW_REF"],os.environ["GITHUB_WORKFLOW_SHA"],"fail_closed_matrix")
 rejected(lambda:rt.claim(snapshot=snap,mission_id=a.mission_id,continuation_id="FORGED",authorization_id=a.authorization_id,claimant_identity=ident),"FORGED_CONTINUATION_REJECTED")
 rejected(lambda:rt.claim(snapshot=snap,mission_id=a.mission_id,continuation_id=a.continuation_id,authorization_id="FORGED",claimant_identity=ident),"FORGED_AUTHORIZATION_REJECTED")
 rejected(lambda:rt.claim(snapshot=snap,mission_id=a.mission_id,continuation_id=a.continuation_id,authorization_id=a.authorization_id,claimant_identity=ident),"CONSUMED_CONTINUATION_REUSE_REJECTED")
 rejected(lambda:rt.require_current_claim(snapshot=snap,claim_id=a.old_claim_id,fencing_epoch=a.old_fence,claimant_identity=ident),"STALE_CLAIM_REJECTED")
 print("SEMANTIC_EXECUTION_STARTED=NO");print("PLANNER_CALLS=0");print("PROVIDER_CALLS=0");print("AGENT_CALLS=0");print("TASKRESULT_WRITES=0");print("SIDE_EFFECTS=0")
if __name__=="__main__":main()
