import os
from unittest.mock import patch
import pytest
from app.services.harness_git_transaction_store import CasConflict
from app.services.harness_durable_execution_v3 import ClaimantIdentity
import scripts.durable_v3_trusted_bootstrap as b

class S:
 def __init__(self,states):self.states=states;self.i=0
 def snapshot(self,m):x=self.states[min(self.i,len(self.states)-1)];self.i+=1;return x
 def read_json(self,ref,sha):return self.states_by_sha[sha].objects.get(ref)
class Snap:
 def __init__(self,sha,h,objects):self.head_sha=sha;self.mission_head=h;self.objects=objects

def test_same_claimant_identity_includes_run_attempt():
 a=ClaimantIdentity("1",1,"w","s","j");b2=ClaimantIdentity("1",2,"w","s","j")
 assert a.to_dict()!=b2.to_dict()

def test_cas_conflict_type_is_not_generic_validation_error():
 assert issubclass(CasConflict,RuntimeError)
