import pytest
from app.services.harness_git_transaction_store import GitApiError,GitRefUpdateRejected,RefUpdateOutcomeUnknown

def test_git_api_error_is_typed_not_string_protocol():
 e=GitApiError(422,"validation","PATCH","/git/refs/heads/harness-state")
 assert e.status==422 and e.method=="PATCH" and e.path.endswith("harness-state")

def classify(expected,candidate,observed,status=422,ambiguous=False):
 if observed==candidate:return "REF_UPDATE_CONFIRMED_SUCCESS"
 if observed!=expected:return "CAS_CONFLICT_CONFIRMED"
 if status==422:return "REF_UPDATE_REJECTED"
 if ambiguous:return "RETRY_BOUNDED"
 return "REF_UPDATE_REJECTED"

@pytest.mark.parametrize("observed,status,ambiguous,want",[
 ("C",None,True,"REF_UPDATE_CONFIRMED_SUCCESS"),
 ("E",None,True,"RETRY_BOUNDED"),
 ("X",None,True,"CAS_CONFLICT_CONFIRMED"),
 ("X",422,False,"CAS_CONFLICT_CONFIRMED"),
 ("E",422,False,"REF_UPDATE_REJECTED")])
def test_expected_candidate_observed_matrix(observed,status,ambiguous,want):
 assert classify("E","C",observed,status,ambiguous)==want

def test_unknown_is_distinct_fail_closed_type():
 assert issubclass(RefUpdateOutcomeUnknown,RuntimeError)
 assert issubclass(GitRefUpdateRejected,RuntimeError)
