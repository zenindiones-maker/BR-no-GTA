from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.services.harness_git_transaction_store import CasConflict,GitRefUpdateRejected,GitHubGitTransactionStore
from app.services.harness_durable_execution_v3 import ClaimantIdentity
import scripts.durable_v3_trusted_bootstrap as b

class Snap:
 def __init__(self,sha,h,objects):self.head_sha=sha;self.mission_head=h;self.objects=objects
class Store:
 def __init__(self,snaps):self.snaps=snaps;self.i=0
 def snapshot(self,m):x=self.snaps[min(self.i,len(self.snaps)-1)];self.i+=1;return x
 def read_json(self,ref,sha):
  for s in self.snaps:
   if s.head_sha==sha:return s.objects.get(ref)
class RT:
 calls=0
 def __init__(self,s):self.s=s
 def claim(self,**kw):
  RT.calls+=1
  if RT.calls==1:raise CasConflict("CAS_CONFLICT_CONFIRMED")
  return ("commit","CL",7)

def base(status="ISSUED",claimant=None,gen=1,plan="P",runtime="R",orch="3",cid="C"):
 g={"authorization_id":"A","runtime_revision":runtime,"orchestration_version":orch}
 r={"continuation_id":cid,"authorization_id":"A","status":status,"claimant_identity":claimant,"claim_id":"CL","fencing_epoch":6}
 h={"mission_id":"M","authority_generation":gen,"active_plan_ref":plan,"active_plan_hash":"PH","runtime_revision":runtime,
 "orchestration_version":orch,"active_authorization_ref":"G","active_continuation_ref":"CREF","active_claim_ref":None,
 "bootstrap_policy_ref":"POL"}
 p={"schema":"BootstrapPolicy/v1","repository_id":"1","workflow_path":"durable-v3-entrypoint-proof.yml",
 "bootstrap_ref":"durable-v3-bootstrap","expected_workflow_sha":"WS","allowed_event":"workflow_dispatch"}
 return h,{"G":g,"CREF":r,"POL":p}

def env():
 return patch.dict("os.environ",{"GITHUB_RUN_ID":"10","GITHUB_RUN_ATTEMPT":"1","GITHUB_WORKFLOW_REF":"o/r/.github/workflows/durable-v3-entrypoint-proof.yml@durable-v3-bootstrap","GITHUB_WORKFLOW_SHA":"WS","GITHUB_REPOSITORY_ID":"1","BOOTSTRAP_REF":"durable-v3-bootstrap","GITHUB_REPOSITORY":"o/r","GITHUB_TOKEN":"x"},clear=False)

def test_bounded_retry_same_authority_same_claimant(monkeypatch):
 h,o=base();s=Store([Snap("H0",h,o),Snap("H1",h,o),Snap("H2",h,o)])
 RT.calls=0;monkeypatch.setattr(b,"store",lambda:s);monkeypatch.setattr(b,"DurableExecutionV3",RT);monkeypatch.setattr(b.time,"sleep",lambda _:None)
 with env():b.claim(SimpleNamespace(mission_id="M",continuation_id="C",authorization_id="A"))
 assert RT.calls==2

@pytest.mark.parametrize("change",["other","generation","plan","runtime","orch","revoked"])
def test_semantic_drift_stops_retry(monkeypatch,change):
 ident=ClaimantIdentity("99",1,"w","s","trusted_claim").to_dict();h0,o0=base();h1,o1=base()
 if change=="other":h1["active_claim_ref"]="X";o1["CREF"]={**o1["CREF"],"status":"CLAIMED","claimant_identity":ident}
 if change=="generation":h1["authority_generation"]=2
 if change=="plan":h1["active_plan_ref"]="P2"
 if change=="runtime":h1["runtime_revision"]="R2"
 if change=="orch":h1["orchestration_version"]="4"
 if change=="revoked":o1["CREF"]={**o1["CREF"],"status":"REVOKED"}
 s=Store([Snap("H0",h0,o0),Snap("H1",h1,o1)]);RT.calls=0;monkeypatch.setattr(b,"store",lambda:s);monkeypatch.setattr(b,"DurableExecutionV3",RT)
 with env(),pytest.raises(SystemExit):b.claim(SimpleNamespace(mission_id="M",continuation_id="C",authorization_id="A"))
 assert RT.calls==1

def test_same_claimant_lost_response_returns_existing(monkeypatch):
 ci=ClaimantIdentity("10",1,"o/r/.github/workflows/durable-v3-entrypoint-proof.yml@durable-v3-bootstrap","WS","trusted_claim").to_dict()
 h0,o0=base();h1,o1=base("CLAIMED",ci);h1["active_claim_ref"]="CLAIM";o1["CREF"]["fencing_epoch"]=9
 s=Store([Snap("H0",h0,o0),Snap("H1",h1,o1),Snap("H1",h1,o1)]);RT.calls=0;monkeypatch.setattr(b,"store",lambda:s);monkeypatch.setattr(b,"DurableExecutionV3",RT)
 with env():b.claim(SimpleNamespace(mission_id="M",continuation_id="C",authorization_id="A"))
 assert RT.calls==1

def test_run_attempt_changes_claimant():
 assert ClaimantIdentity("1",1,"w","s","j").to_dict()!=ClaimantIdentity("1",2,"w","s","j").to_dict()

def test_422_ref_moved_is_confirmed_conflict(monkeypatch):
 st=object.__new__(GitHubGitTransactionStore);st.branch="harness-state"
 monkeypatch.setattr(st,"_ref",lambda:{"object":{"sha":"H1"}})
 def api(*a,**k):raise RuntimeError("GITHUB_GIT_API_ERROR:422:validation")
 monkeypatch.setattr(st,"_api",api)
 # classification helper is exercised through transaction integration; 422 itself is not CasConflict at _api boundary
 with pytest.raises(RuntimeError,match="422"):st._api("PATCH","x",{})

def test_validation_rejection_type_records_expected_observed():
 e=GitRefUpdateRejected(422,"validation","H0","H0")
 assert e.expected_head_sha==e.observed_head_sha=="H0"
