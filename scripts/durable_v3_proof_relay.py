from __future__ import annotations
import argparse,json,os
from app.services.harness_durable_execution_v3 import DurableExecutionV3
from app.services.harness_git_transaction_store import GitHubGitTransactionStore
def main():
 p=argparse.ArgumentParser();p.add_argument("--mission-id",required=True);p.add_argument("--continuation-id",required=True)
 p.add_argument("--authorization-id",required=True);p.add_argument("--workflow-run-id",required=True);p.add_argument("--expected-workflow-sha",required=True);a=p.parse_args()
 s=GitHubGitTransactionStore(repository=os.environ["GITHUB_REPOSITORY"],token=os.environ["GITHUB_TOKEN"])
 snap=s.snapshot(a.mission_id);h=snap.mission_head or {};policy=s.read_json(h.get("bootstrap_policy_ref",""),snap.head_sha)
 if not policy:raise SystemExit("BOOTSTRAP_POLICY_MISSING")
 if policy["expected_workflow_sha"]!=a.expected_workflow_sha:raise SystemExit("BOOTSTRAP_REF_DRIFT")
 grant=s.read_json(h["active_authorization_ref"],snap.head_sha)
 if not grant or grant["authorization_id"]!=a.authorization_id:raise SystemExit("AUTHORIZATION_NOT_CANONICAL")
 receipt={"workflow":policy["workflow_path"],"bootstrap_ref":policy["bootstrap_ref"],
  "expected_workflow_sha":policy["expected_workflow_sha"],"run_id":a.workflow_run_id,
  "result":"ACCEPTED"}
 DurableExecutionV3(s).record_dispatch(snapshot=snap,continuation_id=a.continuation_id,dispatch_receipt=receipt)
 print("DISPATCH_ATTEMPT_RECORDED=PASS")
if __name__=="__main__":main()
